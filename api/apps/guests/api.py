"""Creator side of guest links + org guest campaigns. Every endpoint checks ownership / org role explicitly."""

import csv
import io
from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.learning.models import Curriculum
from apps.orgs.models import Membership, Organization
from apps.orgs.perms import require
from apps.roleplay.models import Scenario

from . import campaigns as camp
from . import qr
from .models import GuestCampaign, GuestLink, Prospect
from .services import claim, csv_safe, public_url, visitor_from

MANAGER_ROLES = ("manager", "admin", "owner")


def _full_manager_memberships(user):
    """Org-wide managers only: unit-scoped managers (admins of a sub-unit) never see org guest links or campaigns,
    matching apps.orgs.perms.require(..., "manager")."""
    return Membership.objects.filter(user=user, role__in=MANAGER_ROLES).exclude(
        role="manager", unit_scoped=True
    )


def _managed_org_ids(user):
    return _full_manager_memberships(user).values("org_id")


def _can_create(user) -> bool:
    return bool(
        user.is_authenticated
        and (user.is_creator or user.is_staff or _full_manager_memberships(user).exists())
    )


def _can_edit(user, link: GuestLink) -> bool:
    """Read access is shared with org managers; changing or deleting someone else's org link needs an org admin."""
    if link.owner_id == user.id:
        return True
    return bool(
        link.org_id
        and Membership.objects.filter(user=user, org_id=link.org_id, role__in=("admin", "owner")).exists()
    )


def _links_for(user):
    return GuestLink.objects.filter(Q(owner=user) | Q(org_id__in=_managed_org_ids(user)))


def _my_link(request, pk) -> GuestLink:
    link = _links_for(request.user).select_related("course", "scenario", "org").filter(pk=pk).first()
    if not link:
        raise Http404
    return link


def _require_creator(request):
    if not _can_create(request.user):
        raise PermissionDenied("creator_access_required")


def _target_courses(user):
    return Curriculum.objects.filter(owner=user, kind=Curriculum.Kind.AUTHORED, published_at__isnull=False)


def _target_scenarios(user):
    return Scenario.objects.filter(Q(source="library") | Q(owner=user))


def _link_out(link: GuestLink) -> dict:
    v = link.visitors
    return {
        "id": link.id,
        "label": link.label,
        "slug": link.slug,
        "url": public_url(link),
        "target_kind": link.target_kind,
        "course": {"id": link.course_id, "title": link.course.title} if link.course_id else None,
        "scenario": {"id": link.scenario_id, "title": link.scenario.title} if link.scenario_id else None,
        "max_uses": link.max_uses,
        "expires_at": link.expires_at,
        "active": link.active,
        "collect_email": link.collect_email,
        "org": link.org.slug if link.org_id else None,
        "state": link.state(),
        "uses": v.count(),
        "opens": link.opens,
        "created_at": link.created_at,
    }


class LinkIn(serializers.Serializer):
    label = serializers.CharField(max_length=120)
    slug = serializers.RegexField(r"^[a-z0-9](?:[a-z0-9-]{2,46}[a-z0-9])$", required=False)
    target_kind = serializers.ChoiceField(choices=["course", "roleplay"])
    course_id = serializers.IntegerField(required=False, allow_null=True)
    scenario_id = serializers.IntegerField(required=False, allow_null=True)
    max_uses = serializers.IntegerField(min_value=1, max_value=100000, required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)
    active = serializers.BooleanField(required=False)
    collect_email = serializers.BooleanField(required=False)
    org = serializers.SlugField(required=False, allow_blank=True, allow_null=True)


def _apply(request, link: GuestLink, d: dict) -> Response | None:
    """Validate + copy fields. Targets must belong to the requesting author (or be built-in scenarios)."""
    if "slug" in d and d["slug"] != link.slug:
        if GuestLink.objects.filter(slug=d["slug"]).exclude(pk=link.pk).exists():
            return Response({"code": "slug_taken"}, status=status.HTTP_409_CONFLICT)
        link.slug = d["slug"]
    if "org" in d:
        if d["org"]:
            link.org = require(request.user, d["org"], "manager").org
        else:
            link.org = None
    kind = d.get("target_kind", link.target_kind)
    link.target_kind = kind
    if kind == "course":
        cid = d.get("course_id", link.course_id)
        course = _target_courses(link.owner).filter(pk=cid).first() if cid else None
        if not course:
            return Response({"code": "bad_course"}, status=status.HTTP_400_BAD_REQUEST)
        link.course, link.scenario = course, None
    else:
        sid = d.get("scenario_id", link.scenario_id)
        sc = _target_scenarios(link.owner).filter(pk=sid).first() if sid else None
        if not sc:
            return Response({"code": "bad_scenario"}, status=status.HTTP_400_BAD_REQUEST)
        link.scenario, link.course = sc, None
    for f in ("label", "max_uses", "expires_at", "active", "collect_email"):
        if f in d:
            setattr(link, f, d[f])
    return None


@api_view(["GET", "POST"])
def links(request):
    _require_creator(request)
    if request.method == "GET":
        qs = _links_for(request.user).select_related("course", "scenario", "org")
        if org := request.query_params.get("org"):
            qs = qs.filter(org__slug=org)
        if course := request.query_params.get("course"):
            qs = qs.filter(course_id=course if course.isdigit() else 0)
        return Response([_link_out(x) for x in qs[:200]])
    ser = LinkIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if GuestLink.objects.filter(owner=request.user).count() >= 500:
        return Response({"code": "too_many_links"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    link = GuestLink(owner=request.user)
    if err := _apply(request, link, ser.validated_data):
        return err
    link.save()
    return Response(_link_out(link), status=status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
def link_detail(request, pk):
    link = _my_link(request, pk)
    if request.method == "GET":
        return Response(_link_out(link))
    if not _can_edit(request.user, link):
        raise PermissionDenied("owner_or_org_admin_only")
    if request.method == "DELETE":
        link.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = LinkIn(data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    if err := _apply(request, link, ser.validated_data):
        return err
    link.save()
    return Response(_link_out(link))


@api_view(["GET"])
def link_qr(request, pk):
    link = _my_link(request, pk)
    matrix = qr.encode(public_url(link), "M")
    if request.query_params.get("as") == "png":
        resp = HttpResponse(qr.png(matrix), content_type="image/png")
        resp["Content-Disposition"] = f'attachment; filename="guest-{link.slug}.png"'
        return resp
    resp = HttpResponse(qr.svg(matrix), content_type="image/svg+xml")
    resp["Content-Disposition"] = f'attachment; filename="guest-{link.slug}.svg"'
    resp["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'"
    return resp


@api_view(["GET"])
def link_stats(request, pk):
    link = _my_link(request, pk)
    v = link.visitors
    n = v.count()
    since = timezone.now() - timedelta(days=13)
    by_day = {
        r["d"]: r["n"]
        for r in v.filter(created_at__gte=since)
        .annotate(d=TruncDate("created_at"))
        .values("d")
        .annotate(n=Count("id"))
    }
    days = [(timezone.localdate() - timedelta(days=i)) for i in range(13, -1, -1)]
    signups = v.filter(claimed_by__isnull=False).count()
    return Response(
        {
            "opens": link.opens,
            "starts": n,
            "completions": v.filter(completed_at__isnull=False).count(),
            "emails": v.exclude(email="").count(),
            "signups": signups,
            "conversion": round(signups / n, 3) if n else None,
            "daily": [{"day": d, "starts": by_day.get(d, 0)} for d in days],
        }
    )


@api_view(["GET"])
def link_export(request, pk):
    link = _my_link(request, pk)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "email", "started", "completed", "answers", "avg_score", "signed_up"])
    for v in link.visitors.annotate(n=Count("attempts")).order_by("created_at"):
        scores = list(v.attempts.values_list("score", flat=True))
        w.writerow(
            [
                csv_safe(v.name),
                csv_safe(v.email),
                v.created_at.isoformat(timespec="minutes"),
                v.completed_at.isoformat(timespec="minutes") if v.completed_at else "",
                v.n,
                round(sum(scores) / len(scores), 2) if scores else "",
                "yes" if v.claimed_by_id else "no",
            ]
        )
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="guest-{link.slug}.csv"'
    return resp


@api_view(["GET"])
def targets(request):
    _require_creator(request)
    return Response(
        {
            "courses": [
                {"id": c.id, "title": c.title or c.goal} for c in _target_courses(request.user)[:200]
            ],
            "scenarios": [
                {"id": s.id, "title": s.title, "emoji": s.emoji}
                for s in _target_scenarios(request.user).order_by("source", "-created_at")[:200]
            ],
            "orgs": [
                {"slug": m.org.slug, "name": m.org.display_name or m.org.name}
                for m in _full_manager_memberships(request.user).select_related("org")
            ],
        }
    )


@api_view(["POST"])
def claim_progress(request):
    """After sign-up: attach the guest's progress (they prove it with their guest token) to the new account."""
    link = GuestLink.objects.filter(slug=str(request.data.get("slug") or "")[:48]).first()
    visitor = visitor_from(request, link) if link else None
    if not visitor:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    out = claim(visitor.id, request.user)
    if out.get("code"):
        return Response(
            out, status=status.HTTP_410_GONE if out["code"].startswith("link_") else status.HTTP_409_CONFLICT
        )
    return Response(out)


# ── Campaigns (org managers) ─────────────────────────────────────────


def _prospect_out(p: Prospect) -> dict:
    out = {
        "id": p.id,
        "company": p.company,
        "email": p.email,
        "industry": p.industry,
        "status": p.status,
        "error": p.error,
        "subject": p.subject,
        "body": p.body,
        "sent_at": p.sent_at,
        "link": None,
        "course_id": p.course_id,
    }
    if p.link_id:
        out["link"] = {
            "id": p.link_id,
            "slug": p.link.slug,
            "url": public_url(p.link),
            "uses": p.link.visitors.count(),
            "signups": p.link.visitors.filter(claimed_by__isnull=False).count(),
        }
    if p.status in (Prospect.Status.READY, Prospect.Status.SENT) and p.link_id:
        out["send_subject"], out["send_body"] = camp.compose(p)
    return out


def _campaign_out(c: GuestCampaign, full=False) -> dict:
    out = {
        "id": c.id,
        "name": c.name,
        "topic": c.topic,
        "language": c.language,
        "created_at": c.created_at,
        "prospects_count": c.prospects.count(),
        "sent": c.prospects.filter(status="sent").count(),
    }
    if full:
        out["prospects"] = [_prospect_out(p) for p in c.prospects.select_related("link", "campaign__org")]
        out["sends_today"] = camp.sends_today(c.org)
        out["sends_per_day"] = camp.org_daily_limit(c.org)
    return out


class CampaignIn(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    topic = serializers.CharField(max_length=200)
    language = serializers.ChoiceField(
        choices=["en", "ta", "tanglish", "hi", "te", "kn", "ml", "bn", "mr", "gu"], default="en"
    )
    prospects = serializers.CharField(max_length=100_000)  # pasted lines / CSV text


def _ai_allowance(user, n: int) -> Response | None:
    from apps.billing.services import PlanLimit, consume

    try:
        consume(user, "lab_ai_per_day", "lab_ai", n)  # atomic, so parallel requests can't all pass
    except PlanLimit as e:
        return Response(e.payload(), status=status.HTTP_402_PAYMENT_REQUIRED)
    return None


def _enqueue(ids):
    from apps.study.jobs import enqueue

    for pid in ids:
        transaction.on_commit(lambda pid=pid: enqueue("apps.guests.campaigns.build_prospect", pid))


@api_view(["GET", "POST"])
def org_campaigns(request, slug):
    me = require(request.user, slug, "manager")
    if request.method == "GET":
        return Response([_campaign_out(c) for c in GuestCampaign.objects.filter(org=me.org)[:100]])
    ser = CampaignIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    rows, errors = camp.parse_prospects(d["prospects"])
    if not rows:
        return Response({"code": "no_prospects", "errors": errors[:20]}, status=status.HTTP_400_BAD_REQUEST)
    if len(rows) > camp.MAX_PROSPECTS:
        return Response(
            {"code": "too_many_prospects", "max": camp.MAX_PROSPECTS}, status=status.HTTP_400_BAD_REQUEST
        )
    if denied := _ai_allowance(request.user, len(rows)):
        return denied
    with transaction.atomic():
        c = GuestCampaign.objects.create(
            org=me.org, created_by=request.user, name=d["name"], topic=d["topic"], language=d["language"]
        )
        ps = Prospect.objects.bulk_create(
            [Prospect(campaign=c, status=Prospect.Status.GENERATING, **r) for r in rows]
        )
        _enqueue(
            [p.id for p in ps] if all(p.id for p in ps) else list(c.prospects.values_list("id", flat=True))
        )
    return Response({**_campaign_out(c, full=True), "errors": errors[:20]}, status=status.HTTP_201_CREATED)


def _my_campaign(request, pk) -> tuple[GuestCampaign, Membership]:
    c = get_object_or_404(GuestCampaign.objects.select_related("org"), pk=pk)
    return c, require(request.user, c.org.slug, "manager")


def _my_prospect(request, pk) -> Prospect:
    p = get_object_or_404(Prospect.objects.select_related("campaign__org", "link"), pk=pk)
    require(request.user, p.campaign.org.slug, "manager")
    return p


@api_view(["GET", "DELETE"])
def campaign_detail(request, pk):
    c, _ = _my_campaign(request, pk)
    if request.method == "DELETE":
        c.delete()  # links + demo courses stay (they may already be in someone's inbox)
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(_campaign_out(c, full=True))


class ProspectPatch(serializers.Serializer):
    subject = serializers.CharField(max_length=160, required=False, allow_blank=True)
    body = serializers.CharField(max_length=4000, required=False, allow_blank=True)


@api_view(["PATCH", "DELETE"])
def prospect_detail(request, pk):
    p = _my_prospect(request, pk)
    if request.method == "DELETE":
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if p.status == Prospect.Status.SENT:
        return Response({"code": "already_sent"}, status=status.HTTP_409_CONFLICT)
    ser = ProspectPatch(data=request.data)
    ser.is_valid(raise_exception=True)
    for f, v in ser.validated_data.items():
        setattr(p, f, " ".join(v.split()) if f == "subject" else v.replace("\r", ""))
    p.save()
    return Response(_prospect_out(p))


@api_view(["POST"])
def prospect_regenerate(request, pk):
    p = _my_prospect(request, pk)
    if p.status in (Prospect.Status.GENERATING, Prospect.Status.SENT):
        return Response(
            {"code": "busy" if p.status == "generating" else "already_sent"}, status=status.HTTP_409_CONFLICT
        )
    if denied := _ai_allowance(request.user, 1):
        return denied
    with transaction.atomic():
        Prospect.objects.filter(pk=p.pk).update(status=Prospect.Status.GENERATING, error="")
        _enqueue([p.id])
    p.refresh_from_db()
    return Response(_prospect_out(p), status=status.HTTP_202_ACCEPTED)


def _locked_send(org_id: int, prospects, sender) -> dict:
    """Send under a platform-wide lock row + the org row lock so parallel clicks can't slip past the daily limits."""
    from .models import GuestAIUsage

    out = {"sent": [], "skipped": {}}
    with transaction.atomic():
        GuestAIUsage.objects.select_for_update().get_or_create(
            key="campaign-send-lock", day=timezone.localdate()
        )
        Organization.objects.select_for_update().get(pk=org_id)
        for p in prospects:
            err = camp.send(p, sender)
            if err:
                out["skipped"][p.id] = err
            else:
                out["sent"].append(p.id)
    return out


@api_view(["POST"])
def prospect_send(request, pk):
    p = _my_prospect(request, pk)
    out = _locked_send(p.campaign.org_id, [p], request.user)
    if out["skipped"]:
        code = out["skipped"][p.id]
        return Response(
            {"code": code},
            status=status.HTTP_429_TOO_MANY_REQUESTS
            if code in ("daily_limit", "account_limit", "global_limit")
            else status.HTTP_409_CONFLICT,
        )
    p.refresh_from_db()
    return Response(_prospect_out(p))


@api_view(["POST"])
def campaign_send_all(request, pk):
    c, _ = _my_campaign(request, pk)
    if request.data.get("confirm") is not True:
        return Response({"code": "confirm_required"}, status=status.HTTP_400_BAD_REQUEST)
    ready = list(c.prospects.filter(status=Prospect.Status.READY).select_related("link", "campaign__org"))
    out = _locked_send(c.org_id, ready, request.user)
    return Response({**out, "campaign": _campaign_out(c, full=True)})
