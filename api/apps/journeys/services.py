"""Journey maths: Day X of N (timezone.localdate), item completion (lesson progress or ticks), overdue / stuck flags."""

from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone

from .models import JourneyItem, JourneyTick

MAX_DAYS = 365
STUCK_OVERDUE = 3  # this many overdue items …
STUCK_LATE_DAYS = 3  # … or one item this many days late → flag for HR


def day_number(start: date, today: date | None = None) -> int:
    """Day 1 is the start date. Uses the server's local date (Asia/Kolkata) so a joiner's day never flips at UTC midnight."""
    return ((today or timezone.localdate()) - start).days + 1


def due_date(start: date, day: int) -> date:
    return start + timedelta(days=day - 1)


def clean_phases(raw, length: int) -> list[dict]:
    """Phases are ordered day ranges inside the journey; overlapping or out-of-range ones are clipped/dropped."""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for p in raw[:20]:
        if not isinstance(p, dict):
            continue
        title = " ".join(str(p.get("title") or "").split())[:80]
        try:
            a, b = int(p.get("start_day")), int(p.get("end_day"))
        except (TypeError, ValueError):
            continue
        a, b = max(1, a), min(length, b)
        if not title or a > b:
            continue
        out.append({"title": title, "start_day": a, "end_day": b})
    out.sort(key=lambda x: x["start_day"])
    kept: list[dict] = []
    for p in out:  # no overlaps: a later phase starts after the previous one ends
        if kept and p["start_day"] <= kept[-1]["end_day"]:
            p["start_day"] = kept[-1]["end_day"] + 1
            if p["start_day"] > p["end_day"]:
                continue
        kept.append(p)
    return kept


def phase_of(phases: list[dict], day: int) -> int | None:
    for i, p in enumerate(phases):
        if p["start_day"] <= day <= p["end_day"]:
            return i
    return None


# ── Completion ───────────────────────────────────────────────────────


def required_subsections(items) -> dict[int, set[int]]:
    """Lesson items → the subsection ids that must be completed (one lesson, or every live lesson of the course)."""
    from apps.learning.models import Subsection

    out: dict[int, set[int]] = {}
    course_ids = {
        i.curriculum_id
        for i in items
        if i.kind == JourneyItem.Kind.LESSON and i.curriculum_id and not i.subsection_id
    }
    by_course: dict[int, set[int]] = {}
    if course_ids:
        for sid, cid in Subsection.objects.filter(
            section__curriculum_id__in=course_ids, archived=False, section__archived=False
        ).values_list("id", "section__curriculum_id"):
            by_course.setdefault(cid, set()).add(sid)
    for i in items:
        if i.kind != JourneyItem.Kind.LESSON:
            continue
        out[i.id] = {i.subsection_id} if i.subsection_id else by_course.get(i.curriculum_id, set())
    return out


def done_items(assignments, items) -> dict[int, dict[int, timezone.datetime | None]]:
    """{assignment_id: {item_id: done_at}} for every finished item. Lesson items complete through normal lesson completion
    (UserSubsectionState), everything else through the learner's ticks."""
    from apps.learning.models import UserSubsectionState

    assignments = list(assignments)
    req = required_subsections(items)
    subs = set().union(*req.values()) if req else set()
    uid_of = {a.id: a.membership.user_id for a in assignments}
    completed: dict[int, dict[int, object]] = {}
    if subs:
        for uid, sid, at in UserSubsectionState.objects.filter(
            user_id__in=set(uid_of.values()), subsection_id__in=subs, status="completed"
        ).values_list("user_id", "subsection_id", "completed_at"):
            completed.setdefault(uid, {})[sid] = at
    out: dict[int, dict[int, object]] = {a.id: {} for a in assignments}
    for aid, iid, at in JourneyTick.objects.filter(assignment_id__in=list(uid_of)).values_list(
        "assignment_id", "item_id", "done_at"
    ):
        out[aid][iid] = at
    for a in assignments:
        mine = completed.get(uid_of[a.id], {})
        for iid, need in req.items():
            if need and need <= mine.keys():
                out[a.id][iid] = max((mine[s] for s in need if mine[s]), default=None)
            else:
                out[a.id].pop(iid, None)  # a stale tick never completes a lesson item
    return out


def status_of(a, items, done: dict, today: date | None = None) -> dict:
    """Per-joiner summary: current day, done/overdue counts, phase status, stuck flag."""
    j = a.journey
    day = day_number(a.start_date, today)
    total = len(items)
    n_done = sum(1 for i in items if i.id in done)
    overdue = [i for i in items if i.id not in done and i.day < day]
    late_days = max((day - i.day for i in overdue), default=0)
    phases = []
    for p in j.phases or []:
        mine = [i for i in items if p["start_day"] <= i.day <= p["end_day"]]
        all_done = all(i.id in done for i in mine)
        if mine and all_done:
            st = "done"
        elif day < p["start_day"]:
            st = "upcoming"
        elif day > p["end_day"]:
            st = "behind" if mine else "done"
        else:
            st = "active"
        phases.append({**p, "status": st, "done": sum(1 for i in mine if i.id in done), "total": len(mine)})
    finished = total > 0 and n_done == total
    return {
        "day": day,
        "length_days": j.length_days,
        "started": day >= 1,
        "ended": day > j.length_days,
        "done": n_done,
        "total": total,
        "overdue": len(overdue),
        "finished": finished,
        "stuck": not finished
        and day >= 1
        and (len(overdue) >= STUCK_OVERDUE or late_days >= STUCK_LATE_DAYS),
        "phase": phase_of(j.phases or [], day),
        "phases": phases,
    }


# ── Who sees what ────────────────────────────────────────────────────


def assignable_documents(org):
    """Knowledge-base / shared documents a learner of this org may read (see orgs.extras.readable_org_documents)."""
    return (
        org.documents.filter(document__isnull=False, status="ready")
        .filter(Q(source="shared") | Q(learners_can_read=True))
        .defer("raw")
    )


def journey_scenario_ids(user):
    """Role-plays in the user's journeys: they may start these even if not in their library (roleplay.api.sessions).
    None when role-play is switched off for them (extras.blocked) or by the journey's own org."""
    from apps.orgs.extras import blocked
    from apps.orgs.models import Organization

    if blocked(user, "roleplay"):
        return JourneyItem.objects.none().values("scenario_id")
    return (
        JourneyItem.objects.filter(
            kind="scenario",
            scenario__isnull=False,
            journey__assignments__membership__user=user,
            journey__assignments__membership__partner=False,
        )
        .exclude(journey__org__in=Organization.objects.filter(features__roleplay=False))
        .values("scenario_id")
    )
