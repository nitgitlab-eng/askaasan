"""Compliance training records (C3): written by the completion hooks (apps.integrations.hooks), read by the cockpit,
the learner's own account page and the v1 API, exported as CSV / Excel / PDF."""

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Membership, TrainingRecord
from .perms import require

KINDS = tuple(TrainingRecord.Kind.values)


def _item_key(kind: str, item) -> int:
    return item.workshop_id if kind == "workshop" else item.id  # one record per workshop, whichever run


def dedupe_key(org, user, kind: str, item) -> str:
    return f"{org.id}:{user.id}:{kind}:{_item_key(kind, item)}"


def _title(kind: str, item) -> str:
    return ((item.workshop.title if kind == "workshop" else getattr(item, "title", "")) or "").strip()[:200]


def _find_certificate(c):
    """The certificate already issued for this completion, if any (issue() may run before or after the hook)."""
    from apps.credentials.models import Certificate

    if c.kind == "workshop":
        keys = [f"{c.user.id}:workshop:{c.item.workshop_id}"]
    else:
        keys = [f"{c.user.id}:{c.kind}:{c.org.id}:{c.item.id}", f"{c.user.id}:{c.kind}:0:{c.item.id}"]
    return Certificate.objects.filter(dedupe__in=keys).order_by("-org_id").first()


def record_completion(c) -> tuple[TrainingRecord, bool]:
    """Idempotent (unique dedupe): the first completion is the record; later repeats return it unchanged."""
    from apps.credentials.services import learner_name, verify_url

    key = dedupe_key(c.org, c.user, c.kind, c.item)
    found = TrainingRecord.objects.filter(dedupe=key).first()
    if found:
        return found, False
    cert = c.certificate or _find_certificate(c)
    assignment = min(c.assignments, key=lambda a: a.created_at) if c.assignments else None
    fk = {"course": "curriculum", "scenario": "scenario", "workshop": "workshop_run", "test": "survey"}[
        c.kind
    ]
    try:
        with transaction.atomic():
            rec = TrainingRecord.objects.create(
                org=c.org,
                org_name=(c.org.display_name or c.org.name)[:120],
                user=c.user,
                learner_name=learner_name(c.user)[:120],
                learner_email=c.user.email,
                kind=c.kind,
                title=_title(c.kind, c.item),
                assignment=assignment,
                assigned_at=assignment.created_at if assignment else None,
                started_at=c.started_at,
                completed_at=c.completed_at or timezone.now(),
                score=c.score,
                minutes=c.minutes,
                certificate=cert,
                certificate_code=cert.code if cert else "",
                verify_url=verify_url(cert) if cert else "",
                dedupe=key,
                backfilled=getattr(c, "backfilled", False),
                **{fk: c.item},
            )
    except IntegrityError:  # a concurrent hook wrote it first
        return TrainingRecord.objects.get(dedupe=key), False
    return rec, True


def certificate_org(cert):
    """The organisation a certificate counts for: its issuer, or the organisation that ran the workshop."""
    if cert.org_id:
        return cert.org
    if cert.kind == "workshop" and cert.workshop_run_id and cert.workshop_run.org_id:
        return cert.workshop_run.org
    return None


def record_certificate(cert) -> TrainingRecord | None:
    """Attach a newly issued certificate to the learner's matching record (single fill)."""
    item_q = {
        "course": Q(curriculum_id=cert.curriculum_id),
        "scenario": Q(scenario_id=cert.scenario_id),
        "test": Q(survey_id=cert.survey_id),
        "workshop": Q(
            workshop_run__workshop_id=cert.workshop_run.workshop_id if cert.workshop_run_id else None
        ),
    }[cert.kind]
    orgs = [cert.org_id] if cert.org_id else []
    if not orgs:  # Aasan-issued: any organisation that holds a record for this item
        orgs = list(Membership.objects.filter(user_id=cert.user_id).values_list("org_id", flat=True))
    rec = (
        TrainingRecord.objects.filter(item_q, user_id=cert.user_id, kind=cert.kind, org_id__in=orgs)
        .filter(certificate__isnull=True)
        .first()
    )
    if rec and TrainingRecord.attach_certificate(rec.pk, cert):
        return TrainingRecord.objects.get(pk=rec.pk)
    return None


# ── Reading ───────────────────────────────────────────────────────────

HEADER = [
    "Learner",
    "Email",
    "Type",
    "Title",
    "Assigned",
    "Started",
    "Completed",
    "Score %",
    "Minutes (est.)",
    "Certificate",
    "Verify",
    "Organisation",
]


def _iso(d):
    return timezone.localtime(d).strftime("%Y-%m-%d %H:%M") if d else ""


def row(r: TrainingRecord) -> dict:
    return {
        "id": r.id,
        "learner": r.learner_name,
        "email": r.learner_email,
        "kind": r.kind,
        "title": r.title,
        "assigned_at": r.assigned_at,
        "started_at": r.started_at,
        "completed_at": r.completed_at,
        "score": round(r.score * 100) if r.score is not None else None,
        "minutes": r.minutes,
        "certificate_code": r.certificate_code,
        "verify_url": r.verify_url,
        "org": r.org_name,
        "backfilled": r.backfilled,
    }


def rows_for(qs) -> list[list]:
    """Spreadsheet / PDF rows in HEADER order."""
    return [
        [
            r.learner_name,
            r.learner_email,
            r.kind,
            r.title,
            _iso(r.assigned_at),
            _iso(r.started_at),
            _iso(r.completed_at),
            round(r.score * 100) if r.score is not None else "",
            r.minutes if r.minutes is not None else "",
            r.certificate_code,
            r.verify_url,
            r.org_name,
        ]
        for r in qs
    ]


def filtered(request, qs):
    """?user=<id>&kind=<kind>&from=YYYY-MM-DD&to=YYYY-MM-DD (completion date, inclusive)."""
    p = request.query_params
    if (uid := p.get("user")) and str(uid).isdigit():
        qs = qs.filter(user_id=int(uid))
    if (kind := p.get("kind")) in KINDS:
        qs = qs.filter(kind=kind)
    for param, lookup in (("from", "completed_at__date__gte"), ("to", "completed_at__date__lte")):
        try:
            d = parse_date(str(p.get(param) or "")[:10])
        except ValueError:  # well-formed but impossible, e.g. 2026-02-31
            d = None
        if d:
            qs = qs.filter(**{lookup: d})
    return qs


def org_records(me):
    """The records this staff member may see: the whole organisation, or a teacher's classes only."""
    from .teach import scope_groups, scoped_learners

    qs = TrainingRecord.objects.filter(org=me.org)
    if scope_groups(me) is not None:
        qs = qs.filter(user_id__in=scoped_learners(me).values("user_id"))
    return qs


EXPORT_MAX = 5000


def _file(qs, fmt: str, title: str, name: str):
    from apps.studio import exports

    rows = rows_for(qs[:EXPORT_MAX])
    if fmt == "xlsx":
        return exports.download(
            exports.workbook([("Training records", HEADER, rows)]), exports.XLSX, f"{name}.xlsx"
        )
    return exports.download(exports.records_pdf(title, HEADER, rows), "application/pdf", f"{name}.pdf")


@api_view(["GET"])
def training_records(request, slug):
    """GET ?page= &export=csv (+ filters) — paged JSON or CSV."""
    from apps.accounts.admin_paging import paged

    me = require(request.user, slug, "manager")
    return paged(request, filtered(request, org_records(me)), row, name=f"training-records-{me.org.slug}")


def _org_file(request, slug, fmt):
    me = require(request.user, slug, "manager")
    title = f"Training records: {me.org.display_name or me.org.name}"
    return _file(filtered(request, org_records(me)), fmt, title, f"training-records-{me.org.slug}")


@api_view(["GET"])
def training_records_xlsx(request, slug):
    return _org_file(request, slug, "xlsx")


@api_view(["GET"])
def training_records_pdf(request, slug):
    return _org_file(request, slug, "pdf")


# ── The learner's own record ──────────────────────────────────────────


def _mine(request):
    return TrainingRecord.objects.filter(user=request.user)


@api_view(["GET"])
def my_training_record(request):
    return Response([row(r) for r in _mine(request)[:500]])


@api_view(["GET"])
def my_training_record_xlsx(request):
    return _file(_mine(request), "xlsx", "My training record", "my-training-record")


@api_view(["GET"])
def my_training_record_pdf(request):
    return _file(_mine(request), "pdf", "My training record", "my-training-record")
