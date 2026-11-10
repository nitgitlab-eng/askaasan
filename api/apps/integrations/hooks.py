"""Completion hooks: the one place that turns "a learner finished something their organisation gave them" into the
things organisations integrate with — a compliance training record (apps.orgs.records) and outbound webhook events
(events.emit).

Callers: signals.py (a lesson completed, a certificate issued), roleplay.services.finish, workshops.services (pass) and
orgs.surveys._submit (knowledge test passed). The public on_* functions only dispatch: the work runs inline when
LEARNING_JOBS_INLINE is set (tests), otherwise after the surrounding transaction commits, as a Celery task when Redis is
configured or in a thread in local dev. A failing hook is logged and never breaks the learner's request."""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

log = logging.getLogger(__name__)


@dataclass
class Completion:
    org: object  # orgs.Organization
    user: object
    kind: str  # course | scenario | workshop | test
    item: object  # Curriculum | Scenario | WorkshopRun | Survey
    completed_at: datetime
    assignments: list = field(default_factory=list)
    started_at: datetime | None = None
    score: float | None = None  # 0..1
    minutes: int | None = None  # estimated time spent
    certificate: object | None = None
    backfilled: bool = False


# ── Entry points (cheap: they only dispatch) ──────────────────────────


def on_lesson_completed(user_id: int, subsection_id: int) -> None:
    _dispatch("lesson", user_id, subsection_id)


def on_roleplay_done(session_id: int) -> None:
    _dispatch("roleplay", session_id)


def on_workshop_passed(session_id: int) -> None:
    _dispatch("workshop", session_id)


def on_test_passed(response_id: int) -> None:
    _dispatch("test", response_id)


def on_certificate(cert_id: int) -> None:
    _dispatch("certificate", cert_id)


def _dispatch(name: str, *args) -> None:
    if getattr(settings, "LEARNING_JOBS_INLINE", False):
        run(name, *args)
        return

    def go():
        if settings.REDIS_URL:
            from .tasks import run_hook

            run_hook.delay(name, *args)
        else:
            from apps.learning.jobs import _thread

            _thread(run, name, *args)

    transaction.on_commit(go)


def run(name: str, *args) -> None:
    try:
        HANDLERS[name](*args)
    except Exception:  # an integration problem must never surface to the learner
        log.exception("integration hook %s failed", name)


# ── Handlers ──────────────────────────────────────────────────────────


def _lesson_minutes(st) -> int:
    """Estimated minutes for one finished lesson: time from first open to completion, 1–60, else 10."""
    if st.started_at and st.completed_at and st.completed_at >= st.started_at:
        return max(1, min(60, int((st.completed_at - st.started_at).total_seconds() // 60)))
    return 10


def course_completions(user, cur) -> list[Completion]:
    """One completion per organisation that assigned `cur` to `user`, if every non-archived lesson is completed."""
    from apps.learning.models import Subsection, UserSubsectionState
    from apps.orgs.api import learner_assignments

    assigns = list(learner_assignments(user).filter(curriculum=cur))
    if not assigns:
        return []
    subs = list(
        Subsection.objects.filter(
            section__curriculum=cur, archived=False, section__archived=False
        ).values_list("id", flat=True)
    )
    states = list(
        UserSubsectionState.objects.filter(
            user=user, subsection_id__in=subs, status=UserSubsectionState.Status.COMPLETED
        )
    )
    if not subs or len(states) < len(subs):
        return []
    scores = [st.score for st in states if st.score is not None]
    ends = [st.completed_at for st in states if st.completed_at]
    starts = [st.started_at or st.completed_at for st in states if st.started_at or st.completed_at]
    by_org = defaultdict(list)
    for a in assigns:
        by_org[a.org_id].append(a)
    return [
        Completion(
            org=alist[0].org,
            user=user,
            kind="course",
            item=cur,
            assignments=alist,
            completed_at=max(ends) if ends else timezone.now(),
            started_at=min(starts) if starts else None,
            score=round(sum(scores) / len(scores), 3) if scores else None,
            minutes=sum(_lesson_minutes(st) for st in states),
        )
        for alist in by_org.values()
    ]


def lesson_completions(user_id: int, subsection_id: int) -> list[Completion]:
    from apps.accounts.models import User
    from apps.learning.models import Subsection

    sub = Subsection.objects.select_related("section__curriculum").filter(pk=subsection_id).first()
    user = User.objects.filter(pk=user_id, is_active=True).first()
    return course_completions(user, sub.section.curriculum) if sub and user else []


def roleplay_completions(session_id: int) -> list[Completion]:
    from apps.orgs.models import Membership
    from apps.roleplay.models import RolePlaySession

    s = (
        RolePlaySession.objects.select_related("assignment__org", "scenario", "user")
        .filter(pk=session_id, status=RolePlaySession.Status.COMPLETED)
        .first()
    )
    if not s or not s.assignment_id or not s.result:
        return []  # personal practice: no organisation to tell
    a = s.assignment
    if not Membership.objects.filter(org_id=a.org_id, user_id=s.user_id, role="learner").exists():
        return []
    end = s.ended_at or timezone.now()
    return [
        Completion(
            org=a.org,
            user=s.user,
            kind="scenario",
            item=s.scenario,
            assignments=[a],
            completed_at=end,
            started_at=s.started_at,
            score=round(int(s.result.get("overall", 0)) / 100, 3),
            minutes=max(1, int((end - s.started_at).total_seconds() // 60)) if s.started_at else None,
        )
    ]


def workshop_completions(session_id: int) -> list[Completion]:
    from apps.workshops.models import WorkshopSession

    s = (
        WorkshopSession.objects.select_related("run__workshop", "run__org", "user", "certificate")
        .filter(pk=session_id, passed=True)
        .first()
    )
    if not s or not s.run.org_id:
        return []  # public runs belong to no organisation
    end = s.ended_at or timezone.now()
    spent = int((end - s.started_at).total_seconds() // 60) if s.started_at else 0
    return [
        Completion(
            org=s.run.org,
            user=s.user,
            kind="workshop",
            item=s.run,
            completed_at=end,
            started_at=s.started_at,
            score=s.final_score,
            minutes=max(1, spent) if spent else s.run.workshop.duration_minutes,
            certificate=s.certificate,
        )
    ]


def knowledge_test_completions(response_id: int) -> list[Completion]:
    from apps.orgs.models import SurveyResponse

    r = (
        SurveyResponse.objects.select_related("survey__org", "user")
        .filter(pk=response_id, passed=True)
        .first()
    )
    if not r or not r.user_id:
        return []  # anonymous answers are never tied to a person
    return [
        Completion(
            org=r.survey.org,
            user=r.user,
            kind="test",
            item=r.survey,
            completed_at=r.submitted_at,
            score=round(r.score / r.max_score, 3) if r.score is not None and r.max_score else None,
        )
    ]


def _fanout(c: Completion) -> None:
    """A completion → its training record; the first time only, the organisation's webhook events (one transaction,
    so a retried hook never records without telling or tells twice)."""
    from apps.orgs.records import record_completion

    with transaction.atomic():
        rec, created = record_completion(c)
        if created:
            _emit_completion(c, rec)


def _emit_completion(c: Completion, rec) -> None:
    from .events import emit, learner

    who = learner(c.user)
    done = {"completed_at": rec.completed_at.isoformat(), "score": rec.score}
    if c.kind == "course":
        emit(
            c.org,
            "course.completed",
            {"course": {"id": c.item.id, "title": rec.title}, "learner": who, "minutes": rec.minutes, **done},
        )
    if c.kind in ("course", "scenario"):
        for a in c.assignments:
            emit(
                c.org,
                "assignment.completed",
                {
                    "assignment": {"id": a.id, "kind": a.kind, "title": rec.title, "due_at": _iso(a.due_at)},
                    "learner": who,
                    **done,
                },
            )
    if c.kind == "workshop":
        emit(
            c.org,
            "workshop.passed",
            {"workshop": {"run_id": c.item.id, "title": rec.title}, "learner": who, **done},
        )


def _iso(d):
    return d.isoformat() if d else None


def _certificate(cert_id: int) -> None:
    """A certificate was issued: attach it to the learner's training record and tell the organisation."""
    from apps.credentials.models import Certificate
    from apps.credentials.services import verify_url
    from apps.orgs.models import Membership
    from apps.orgs.records import certificate_org, record_certificate

    from .events import emit, learner

    cert = (
        Certificate.objects.select_related("org", "workshop_run__org", "user__profile")
        .filter(pk=cert_id)
        .first()
    )
    if not cert:
        return
    record_certificate(cert)
    org = certificate_org(cert)
    if org and Membership.objects.filter(org=org, user_id=cert.user_id).exists():
        emit(
            org,
            "certificate.issued",
            {
                "certificate": {
                    "code": cert.code,
                    "kind": cert.kind,
                    "title": cert.title,
                    "issued_at": cert.issued_at.isoformat(),
                    "verify_url": verify_url(cert),
                },
                "learner": learner(cert.user),
            },
        )


def on_member_joined(m) -> None:
    """orgs.api._join created a membership."""
    from .events import emit, learner

    emit(
        m.org,
        "member.joined",
        {"member": {"id": m.id, "role": m.role, **learner(m.user)}, "joined_at": _iso(m.joined_at)},
    )


def _each(builder):
    def handler(*args):
        for c in builder(*args):
            _fanout(c)

    return handler


HANDLERS = {
    "lesson": _each(lesson_completions),
    "roleplay": _each(roleplay_completions),
    "workshop": _each(workshop_completions),
    "test": _each(knowledge_test_completions),
    "certificate": _certificate,
}
