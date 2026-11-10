"""Issuing certificates (automatically on course completion, or by an org manager with evidence) and their outputs."""

import logging
import re

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q

from .models import Certificate

log = logging.getLogger(__name__)
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{20,40}$")
AASAN = "Aasan"
RESERVED = ("aasan", "ஆசான்")  # an organisation may not issue under (or containing) our name


class ReservedIssuer(Exception):
    pass


def pass_score() -> float:
    return float(getattr(settings, "CERT_PASS_SCORE", 0.6))


def org_issuer_name(org) -> str:
    """The organisation's public name for certificates; refuses names that could pass as Aasan itself."""
    name = (org.display_name or org.name or "").strip()[:120]
    if not name or any(r in name.casefold() for r in RESERVED):
        raise ReservedIssuer(name)
    return name


def course_author(cur) -> str:
    """Who made the course, shown on the certificate so readers can judge it ("Course by …")."""
    if getattr(cur, "template_org_id", None):
        o = cur.template_org
        return (o.display_name or o.name)[:120]
    name = (getattr(getattr(cur.owner, "profile", None), "display_name", "") or "").strip()
    return name[:120] or "an Aasan creator"


def learner_name(user) -> str:
    name = (getattr(getattr(user, "profile", None), "display_name", "") or "").strip()
    return name[:120] or "Aasan learner"  # never fall back to the email: it would be public


def verify_url(cert) -> str:
    return f"{settings.FRONTEND_URL}/verify/{cert.code}"


def issue(user, kind: str, item, *, org=None, issued_by=None, detail=None) -> tuple[Certificate, bool]:
    """Idempotent: one certificate per learner + kind + issuer + item, even under races (unique `dedupe`)."""
    title = (getattr(item, "title", "") or getattr(item, "goal", "") or "").strip()[:200]
    dedupe = f"{user.id}:{kind}:{org.id if org else 0}:{item.id}"
    if kind == "workshop":  # item is the run; one certificate per workshop, whichever run it was passed in
        org, title = None, item.workshop.title.strip()[:200]
        dedupe = f"{user.id}:workshop:{item.workshop_id}"
    found = Certificate.objects.filter(dedupe=dedupe).first()
    if found:
        return found, False
    fk = {"course": "curriculum", "scenario": "scenario", "test": "survey", "workshop": "workshop_run"}[kind]
    issuer = org_issuer_name(org) if org else AASAN  # raises ReservedIssuer
    author = course_author(item) if kind == "course" else ""
    try:
        with transaction.atomic():
            cert = Certificate.objects.create(
                user=user,
                kind=kind,
                title=title,
                learner_name=learner_name(user),
                org=org,
                issuer_name=issuer,
                author_name=author,
                dedupe=dedupe,
                issuer_type="organisation" if org else "aasan",
                issuer_slug=org.slug if org else "",
                issued_by=issued_by,
                detail=detail or {},
                **{fk: item},
            )
    except IntegrityError:
        return Certificate.objects.get(dedupe=dedupe), False
    return cert, True


def course_completed(user, cur) -> bool:
    """Passed, not just clicked through: every non-archived lesson COMPLETED with score >= CERT_PASS_SCORE and at
    least one graded attempt on that lesson's activities. Never for a course the learner owns/authored."""
    from apps.learning.models import ActivityAttempt, Subsection, UserSubsectionState

    if cur.owner_id == user.id:
        return False
    subs = list(
        Subsection.objects.filter(
            section__curriculum=cur, archived=False, section__archived=False
        ).values_list("id", flat=True)
    )
    if not subs:
        return False
    passed = set(
        UserSubsectionState.objects.filter(
            user=user,
            subsection_id__in=subs,
            status=UserSubsectionState.Status.COMPLETED,
            score__gte=pass_score(),
        ).values_list("subsection_id", flat=True)
    )
    from apps.study.models import FastTrackRun

    tried = set(
        ActivityAttempt.objects.filter(
            user=user, activity__subsection_id__in=subs, activity__kind="lesson"
        ).values_list("activity__subsection_id", flat=True)
    )
    # A fast-track check the learner themself passed (graded on the server) is graded evidence too.
    tried |= set(
        FastTrackRun.objects.filter(user=user, subsection_id__in=subs, passed=True).values_list(
            "subsection_id", flat=True
        )
    )
    if not all(s in passed and s in tried for s in subs):
        return False
    from apps.adaptive.services import certificate_ok

    return certificate_ok(user, cur)  # adaptive learners: every critical concept mastered too


def assigning_org(user, cur):
    """An organisation the learner belongs to that assigned this course to them (whole org or one of their classes)."""
    from apps.orgs.models import Assignment, Membership

    for m in Membership.objects.filter(user=user).select_related("org"):
        if (
            Assignment.objects.filter(org=m.org, curriculum=cur)
            .filter(Q(group__isnull=True) | Q(group__members=m))
            .exists()
        ):
            return m.org
    return None


def maybe_issue_course(user, cur):
    """Automatic course certificate: Aasan issues it only for catalog-approved courses; otherwise only an organisation
    that assigned the course to the learner does (issuer = that organisation). Own/self-authored courses never qualify."""
    try:
        if not course_completed(user, cur):
            return
        if cur.catalog_status == cur.CatalogStatus.APPROVED:
            org = None
        elif not (org := assigning_org(user, cur)):
            return
        from apps.adaptive.models import LearnerPath
        from apps.adaptive.services import course_mastery_snapshot

        detail = (
            {"mastery": course_mastery_snapshot(user, cur)}
            if LearnerPath.objects.filter(user=user, curriculum=cur).exists()
            else None
        )
        try:
            cert, created = issue(user, "course", cur, org=org, detail=detail)
        except ReservedIssuer:
            log.warning("org %s has a reserved display name; certificate not issued", org.id if org else None)
            return
        if created:
            from apps.game.services import notify

            notify(user, "certificate", f"🎓 {cert.title}"[:160], "", "/certificates")
    except Exception:
        log.exception("certificate issue failed")


# ── Org managers: evidence-based issuing ─────────────────────────────


def _assigned(org, m):
    from apps.orgs.models import Assignment

    # same rule as orgs.api.learner_assignments: whole-org assignments don't reach partner members, only their groups
    whole_org = Q(group__isnull=True) if not m.partner else Q(pk__in=[])
    return Assignment.objects.filter(org=org).filter(whole_org | Q(group__members=m)).distinct()


def eligible(org, m) -> dict:
    """What a manager may certify for member `m`: assigned courses they completed, assigned scenarios they finished,
    and this org's knowledge tests they passed (named tests only — anonymous answers can't be tied to a person)."""
    from apps.orgs.models import Survey, SurveyResponse
    from apps.roleplay.models import RolePlaySession

    user = m.user
    a = _assigned(org, m)
    courses = [
        c
        for c in {x.curriculum for x in a.filter(curriculum__isnull=False).select_related("curriculum")}
        if course_completed(user, c)
    ]
    done_sc = set(
        RolePlaySession.objects.filter(user=user, status="completed").values_list("scenario_id", flat=True)
    )
    scenarios = [
        x.scenario
        for x in a.filter(scenario__isnull=False).select_related("scenario")
        if x.scenario_id in done_sc
    ]
    passed = SurveyResponse.objects.filter(
        survey__org=org, survey__kind="test", survey__anonymous=False, user=user, passed=True
    )
    tests = Survey.objects.filter(pk__in=passed.values("survey_id"))
    issued = set(Certificate.objects.filter(user=user, org=org).values_list("dedupe", flat=True))

    def row(kind, item):
        return {
            "kind": kind,
            "id": item.id,
            "title": (getattr(item, "title", "") or getattr(item, "goal", ""))[:200],
            "issued": f"{user.id}:{kind}:{org.id}:{item.id}" in issued,
        }

    return {
        "course": [row("course", c) for c in courses],
        "scenario": [row("scenario", s) for s in dict.fromkeys(scenarios)],
        "test": [row("test", t) for t in tests],
    }


def best_pct(org, user, survey) -> int | None:
    from apps.orgs.models import SurveyResponse

    best = None
    for r in SurveyResponse.objects.filter(survey=survey, user=user, passed=True):
        if r.max_score:
            pct = round(100 * (r.score or 0) / r.max_score)
            best = pct if best is None else max(best, pct)
    return best


# ── Outputs ──────────────────────────────────────────────────────────


def public_out(c) -> dict:
    """The ONLY fields the public verification page shows (a workshop certificate adds its planned duration)."""
    out = {
        "code": c.code,
        "learner": c.learner_name,
        "title": c.title,
        "kind": c.kind,
        "issuer": c.issuer_name,
        "issued_by_type": c.issuer_type,
        "org": c.issuer_slug or None,
        "author": c.author_name,
        "issued_at": c.issued_at,
        "verified": True,
        "verify_url": verify_url(c),
    }
    if c.kind == "workshop":
        out["duration_minutes"] = (c.detail or {}).get("minutes")
    return out


def owner_out(c) -> dict:
    return {
        **public_out(c),
        "id": c.id,
        "hidden": c.hidden,
        "revoked": c.revoked_at is not None,
        "revoked_at": c.revoked_at,
        "detail": c.detail,
        "verified": c.revoked_at is None and not c.hidden,
    }


def manager_out(c) -> dict:
    return {
        "id": c.id,
        "learner": c.learner_name,
        "title": c.title,
        "kind": c.kind,
        "issued_at": c.issued_at,
        "revoked": c.revoked_at is not None,
        "issued_by_org": True,
    }
