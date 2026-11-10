"""Adaptive learning glue: mastery from answers, a learner's path (built and re-planned), completion gating and the
certificate concept check. Only courses where the learner has a LearnerPath are adaptive; everything else behaves as
before."""

import logging

from django.db import transaction
from django.db.models import Avg
from django.utils import timezone

from apps.learning.models import ActivityAttempt, Curriculum, Subsection, UserSubsectionState
from apps.review.scheduling import bkt_update, guess_for

from . import graph, planner
from .models import ActivityConcept, Concept, ConceptEdge, ConceptLink, ConceptMastery, LearnerPath, PathItem

log = logging.getLogger(__name__)
PRACTICE_ANSWERS_ENOUGH = 8  # first-attempt practice answers that close a practice step even if mastery lags


# ── mastery ──────────────────────────────────────────────────────────


def _concept_for(activity) -> Concept | None:
    tag = ActivityConcept.objects.filter(activity=activity).select_related("concept").first()
    if tag:
        return tag.concept
    link = ConceptLink.objects.filter(subsection_id=activity.subsection_id).select_related("concept").first()
    return link.concept if link else None


def _bump(user, concept, correct: bool, p_guess: float) -> None:
    with transaction.atomic():
        rec, _ = ConceptMastery.objects.select_for_update().get_or_create(user=user, concept=concept)
        rec.p_known = bkt_update(rec.p_known, correct, p_guess)
        rec.observations += 1
        rec.save()


def observe(user, activity, score: float) -> None:
    """A FIRST attempt at an activity (callers make sure): move that concept's estimate. Retries after the answer was
    revealed would only inflate it."""
    from apps.review.services import PASS

    concept = _concept_for(activity)
    if not concept:
        return
    _bump(user, concept, score >= PASS, guess_for(activity.type, len(activity.payload.get("options", []))))
    if activity.kind == "practice":
        _maybe_close_practice(user, activity.subsection_id)


def observe_lesson(user, sub, score: float) -> None:
    """A first answer to the AI tutor's open check question inside a lesson (no Activity row): the lesson's main
    concept, graded like an open answer (low guess rate)."""
    from apps.review.services import PASS

    link = ConceptLink.objects.filter(subsection=sub).select_related("concept").first()
    if link:
        _bump(user, link.concept, score >= PASS, guess_for("open_input"))


def _seed(user, concept, correct: bool) -> None:
    """A pre-test answer: a strong, quick signal (counts as two observations) before any lesson."""
    with transaction.atomic():
        rec, _ = ConceptMastery.objects.select_for_update().get_or_create(user=user, concept=concept)
        rec.p_known = max(rec.p_known, 0.9) if correct else min(rec.p_known, 0.15)
        rec.observations += 2
        rec.save()


def on_checkpoint(user, cur, kind: str, items: list[dict], review: list[dict]) -> None:
    """Course pre-test seeds mastery (it is the diagnostic); the post-test counts like graded answers. Then re-plan."""
    try:
        graph.ensure(cur)
        by_title = {}
        subs = Subsection.objects.filter(section__curriculum=cur, archived=False).select_related("section")
        for s in subs.order_by("-section__order", "-order"):  # a section title maps to its first lesson
            by_title[s.section.title.strip().lower()] = s.id
        for s in subs:  # lesson titles win over section titles
            by_title[s.title.strip().lower()] = s.id
        first = {}
        for lk in ConceptLink.objects.filter(subsection__section__curriculum=cur).select_related("concept"):
            first.setdefault(lk.subsection_id, lk.concept)
        ok = {r["id"]: r["ok"] for r in review}
        for q in items:
            concept = first.get(by_title.get(str(q.get("lesson", "")).strip().lower()))
            if not concept or q["id"] not in ok:
                continue
            if kind == "pre":
                _seed(user, concept, ok[q["id"]])
            else:
                _bump(user, concept, ok[q["id"]], guess_for("quiz", len(q["options"])))
        if path := LearnerPath.objects.filter(user=user, curriculum=cur).first():
            replan(path)
    except Exception:
        log.exception("adaptive checkpoint update failed")


def learner_for(user, cur, path: LearnerPath | None = None) -> planner.Learner:
    from apps.study.models import CheckpointAttempt

    mastery = {
        m.concept.key: planner.Mastery(m.p_known, m.observations)
        for m in ConceptMastery.objects.filter(user=user, concept__curriculum=cur).select_related("concept")
    }
    learner = planner.Learner(mastery=mastery)
    if path:
        for it in path.items.filter(kind=PathItem.Kind.REMEDIATION).only("subsection_id", "status", "reason"):
            if it.status == PathItem.Status.DONE:
                learner.remediated.add(it.subsection_id)
            elif it.reason == "retry":
                learner.refused.add(it.subsection_id)
    learner.final_done = CheckpointAttempt.objects.filter(user=user, curriculum=cur, kind="post").exists()
    return learner


def _syllabus(user, cur) -> tuple[list[planner.Lesson], dict[str, set[str]]]:
    subs = list(
        Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False).order_by(
            "section__order", "order"
        )
    )
    links: dict[int, list[str]] = {}
    for lk in ConceptLink.objects.filter(subsection__in=subs).select_related("concept"):
        links.setdefault(lk.subsection_id, []).append(lk.concept.key)
    states = dict(
        UserSubsectionState.objects.filter(user=user, subsection__in=subs).values_list(
            "subsection_id", "status"
        )
    )
    lessons = [
        planner.Lesson(s.id, tuple(links.get(s.id, ())), states.get(s.id, "not_started")) for s in subs
    ]
    prereqs: dict[str, set[str]] = {}
    for e in ConceptEdge.objects.filter(concept__curriculum=cur).select_related("prereq", "concept"):
        prereqs.setdefault(e.concept.key, set()).add(e.prereq.key)
    return lessons, prereqs


def _as_items(path) -> list[planner.Item]:
    return [
        planner.Item(i.kind, i.subsection_id, i.concept.key if i.concept else "", i.status, i.reason)
        for i in path.items.select_related("concept")
    ]


# ── the path ─────────────────────────────────────────────────────────


def replan(path: LearnerPath, *, refused: int | None = None) -> dict[str, int]:
    """Recompute the learner's path. Done steps stay done; only what is still ahead can change."""
    cur = path.curriculum
    with transaction.atomic():
        path = LearnerPath.objects.select_for_update().get(pk=path.pk)
        lessons, prereqs = _syllabus(path.user, cur)
        learner = learner_for(path.user, cur, path)
        if refused:
            learner.refused.add(refused)
        old = _as_items(path)
        new = planner.plan(lessons, prereqs, learner)
        concepts = {c.key: c for c in Concept.objects.filter(curriculum=cur)}
        done_at = {(i.kind, i.subsection_id): i.done_at for i in path.items.all() if i.done_at}
        path.items.all().delete()
        now = timezone.now()
        PathItem.objects.bulk_create(
            PathItem(
                path=path,
                order=n,
                kind=it.kind,
                subsection_id=it.subsection_id,
                concept=concepts.get(it.concept),
                status=it.status,
                reason=it.reason,
                done_at=done_at.get((it.kind, it.subsection_id)) or (now if it.status == "done" else None),
            )
            for n, it in enumerate(new)
        )
        diff = planner.changes(old, new)
        if old and any(diff.values()):
            path.version += 1
            path.reason = ";".join(f"{k}={v}" for k, v in diff.items() if v)
            path.replanned_at = now
            path.save(update_fields=["version", "reason", "replanned_at"])
    return diff


def get_path(user, cur: Curriculum, *, create: bool = True) -> LearnerPath | None:
    path = LearnerPath.objects.filter(user=user, curriculum=cur).first()
    if path or not create or cur.status != Curriculum.Status.READY:
        return path
    graph.ensure(cur)
    path, made = LearnerPath.objects.get_or_create(user=user, curriculum=cur)
    if made:
        replan(path)
    return path


def on_progress(user, sub: Subsection) -> None:
    """A lesson was completed (normally or by skip-check): re-plan if this course is adaptive for the learner."""
    try:
        if path := LearnerPath.objects.filter(user=user, curriculum_id=sub.section.curriculum_id).first():
            replan(path)
    except Exception:
        log.exception("adaptive re-plan failed")


def _practice_stats(user, sub_id: int) -> tuple[int, float | None]:
    firsts = {}
    for a in ActivityAttempt.objects.filter(
        user=user, activity__subsection_id=sub_id, activity__kind="practice"
    ).order_by("created_at", "id"):
        firsts.setdefault(a.activity_id, a.score)
    return len(firsts), (sum(firsts.values()) / len(firsts) if firsts else None)


def _maybe_close_practice(user, sub_id: int) -> None:
    item = (
        PathItem.objects.filter(
            path__user=user,
            subsection_id=sub_id,
            kind=PathItem.Kind.REMEDIATION,
            status=PathItem.Status.PENDING,
        )
        .select_related("path", "concept")
        .first()
    )
    if not item:
        return
    answered, _ = _practice_stats(user, sub_id)
    p = (
        ConceptMastery.objects.filter(user=user, concept=item.concept)
        .values_list("p_known", flat=True)
        .first()
        if item.concept
        else None
    )
    if (p is not None and p >= planner.REMEDIATED) or answered >= PRACTICE_ANSWERS_ENOUGH:
        PathItem.objects.filter(pk=item.pk).update(status=PathItem.Status.DONE, done_at=timezone.now())
        replan(item.path)


def gate(user, sub: Subsection, score: float | None, total: int) -> tuple[bool, float | None, dict | None]:
    """May this lesson be completed with this score? → (allowed, score to record, remediation step if refused).
    Adaptive courses only: a lesson below the pass mark needs a practice step first; after practice, the better of
    the lesson score and the practice score is recorded."""
    from apps.credentials.services import pass_score

    cur = sub.section.curriculum
    path = LearnerPath.objects.filter(user=user, curriculum=cur).first()
    if not path or not total or score is None or score >= pass_score():
        return True, score, None
    if cur.kind == Curriculum.Kind.AUTHORED and cur.owner_id == user.id:  # authors trying their own course
        return True, score, None
    if path.items.filter(
        subsection=sub, kind=PathItem.Kind.REMEDIATION, status=PathItem.Status.DONE
    ).exists():
        _, practice = _practice_stats(user, sub.id)
        return True, max(score, practice or 0.0), None
    replan(path, refused=sub.id)
    return False, score, {"kind": "remediation", "subsection_id": sub.id, "reason": "retry"}


def certificate_ok(user, cur) -> bool:
    """Adaptive learners also need every critical concept mastered (non-adaptive courses: unchanged)."""
    path = LearnerPath.objects.filter(user=user, curriculum=cur).first()
    if not path:
        return True
    critical = list(Concept.objects.filter(curriculum=cur, critical=True).values_list("key", flat=True))
    return planner.critical_mastered(critical, learner_for(user, cur))


def generation_context(cur) -> str:
    """For the owner's own course: their goal, and what they already know or find hard, so new lessons build toward
    the goal, skip what's known and recap what's shaky."""
    from .models import LearningGoal

    goal = LearningGoal.objects.filter(curriculum=cur).first()
    bits = []
    if goal and goal.scenario:
        bits.append(
            f"The learner's goal: {goal.scenario.get('title', '')}: {goal.scenario.get('deliverable', '')}. "
            "Tie examples and practice to this goal."
        )
        if goal.constraints.get("no_code"):
            bits.append("No programming exercises: use tools and no-code steps.")
    rows = list(
        ConceptMastery.objects.filter(
            user=cur.owner, concept__curriculum=cur, observations__gte=planner.OFFER_OBS
        )
        .select_related("concept")
        .order_by("-p_known")
    )
    known = [r.concept.title for r in rows if r.p_known >= planner.KNOWN][:5]
    weak = [r.concept.title for r in rows if r.p_known < planner.WEAK][:5]
    if known:
        bits.append(f"They already know: {', '.join(known)} (don't re-teach; build on it).")
    if weak:
        bits.append(f"They find these hard: {', '.join(weak)} (recap briefly before building on them).")
    return " ".join(bits)


# ── output ───────────────────────────────────────────────────────────


def _changes(reason: str) -> dict[str, int]:
    out = {}
    for part in filter(None, (reason or "").split(";")):
        k, _, v = part.partition("=")
        if v.isdigit():
            out[k] = int(v)
    return out


def path_out(path: LearnerPath) -> dict:
    cur = path.curriculum
    items = list(path.items.select_related("subsection", "concept"))
    lessons = {
        s.id: s
        for s in Subsection.objects.filter(section__curriculum=cur).only(
            "id", "title", "objective", "lesson_status"
        )
    }
    open_found = False
    out = []
    for it in items:
        sub = lessons.get(it.subsection_id)
        current = it.status == PathItem.Status.PENDING and not open_found
        open_found = open_found or current
        out.append(
            {
                "id": it.id,
                "kind": it.kind,
                "status": it.status,
                "current": current,
                "reason": it.reason,
                "subsection": {"id": sub.id, "title": sub.title, "objective": sub.objective} if sub else None,
                "concept": {"key": it.concept.key, "title": it.concept.title} if it.concept else None,
            }
        )
    pending = [i for i in out if i["status"] == "pending"]
    return {
        "curriculum_id": cur.id,
        "version": path.version,
        "changes": _changes(path.reason),
        "replanned_at": path.replanned_at,
        "items": out,
        "remaining": len(pending),
        "done": len(out) - len(pending),
    }


def skill_map(user, cur) -> dict:
    learner = learner_for(user, cur)
    concepts = list(Concept.objects.filter(curriculum=cur))
    edges = ConceptEdge.objects.filter(concept__curriculum=cur).values_list("prereq__key", "concept__key")
    lessons: dict[str, list[int]] = {}
    for key, sub_id in ConceptLink.objects.filter(concept__curriculum=cur).values_list(
        "concept__key", "subsection_id"
    ):
        lessons.setdefault(key, []).append(sub_id)
    rows = []
    for c in concepts:
        m = learner.m(c.key)
        state = (
            "mastered"
            if m.p >= planner.MASTERED
            else "weak"
            if planner.is_weak(m)
            else ("learning" if m.obs else "new")
        )
        rows.append(
            {
                "key": c.key,
                "title": c.title,
                "description": c.description,
                "critical": c.critical,
                "p_known": round(m.p, 3),
                "observations": m.obs,
                "state": state,
                "lessons": lessons.get(c.key, []),
            }
        )
    critical = [r for r in rows if r["critical"]]
    return {
        "concepts": rows,
        "edges": [{"prereq": p, "concept": c} for p, c in edges],
        "mastered": sum(1 for r in rows if r["state"] == "mastered"),
        "total": len(rows),
        "critical_mastered": sum(1 for r in critical if r["state"] == "mastered"),
        "critical_total": len(critical),
    }


def practice_score(user, sub_id: int) -> float | None:
    return _practice_stats(user, sub_id)[1]


def course_mastery_snapshot(user, cur) -> dict:
    """Small mastery summary stored on a certificate as evidence."""
    rows = ConceptMastery.objects.filter(user=user, concept__curriculum=cur, concept__critical=True)
    return {
        "concepts": rows.count(),
        "avg_mastery": round(rows.aggregate(a=Avg("p_known"))["a"] or 0.0, 3),
    }
