"""Skill mapping and the adaptive recommender (deterministic, no AI cost)."""

import re
from datetime import timedelta

from django.utils import timezone

from .models import CuratedPath, PathEnrollment, Skill, UserSkill


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).casefold()).strip()


def skill_index() -> list[tuple[Skill, list[str]]]:
    return [(s, [_norm(s.name), *(_norm(k) for k in s.keywords)]) for s in Skill.objects.filter(active=True)]


def match_skills(texts, index=None) -> set[str]:
    """Free-text course/lesson skills → taxonomy slugs."""
    index = index or skill_index()
    out = set()
    for t in texts or []:
        n = _norm(t)
        if not n:
            continue
        for s, keys in index:
            if any(k and (k in n or n in k) for k in keys):
                out.add(s.slug)
    return out


def skill_mastery(user, index=None) -> dict[str, float]:
    """Average BKT mastery per taxonomy skill, from the lessons the learner has practised."""
    from apps.review.models import MasteryRecord

    index = index or skill_index()
    acc: dict[str, list[float]] = {}
    for m in MasteryRecord.objects.filter(user=user).select_related("subsection__section__curriculum"):
        sub = m.subsection
        for slug in match_skills((sub.skills or []) + [sub.title], index) or match_skills(
            sub.section.curriculum.skills, index
        ):
            acc.setdefault(slug, []).append(m.p_known)
    return {k: round(sum(v) / len(v), 3) for k, v in acc.items()}


def user_skill_rows(user) -> dict[str, UserSkill]:
    return {us.skill.slug: us for us in UserSkill.objects.filter(user=user).select_related("skill")}


def recommend(user, limit: int = 6) -> list[dict]:
    from apps.accounts.preferences import upgrade
    from apps.learning.models import Curriculum, LessonFeedback, Subsection, UserSubsectionState
    from apps.review.models import MasteryRecord, ReviewCard

    adaptive = upgrade(user.preferences.data)["learning"].get("adaptive", True)
    index = skill_index()
    prefs = user_skill_rows(user)
    hidden = {k for k, v in prefs.items() if v.hidden}
    followed = [
        k for k, v in sorted(prefs.items(), key=lambda kv: kv[1].order) if v.followed and not v.hidden
    ]
    out: list[dict] = []

    def add(kind, score, title, link, why_key, **params):
        out.append(
            {
                "kind": kind,
                "score": round(score, 1),
                "title": title,
                "link": link,
                "why": {"key": why_key, "params": params},
            }
        )

    due = ReviewCard.objects.filter(user=user, due__lte=timezone.now()).count()
    if due:
        add("review", 95, "Review", "/review", "reviewDue", n=due)
    st = (
        UserSubsectionState.objects.filter(user=user, status=UserSubsectionState.Status.IN_PROGRESS)
        .select_related("subsection__section__curriculum")
        .order_by("-started_at")
        .first()
    )
    if st:
        sub = st.subsection
        add(
            "continue",
            90,
            sub.title,
            f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}",
            "continue",
            course=sub.section.curriculum.title,
        )
    if not adaptive:
        return sorted(out, key=lambda x: -x["score"])[:limit]

    def skill_bonus(sub) -> tuple[float, set[str]]:
        slugs = match_skills((sub.skills or []) + [sub.title], index)
        if slugs & hidden:
            return -999, slugs
        return (12 if slugs & set(followed) else 0), slugs

    # Weak spots: practised but not yet mastered
    for m in (
        MasteryRecord.objects.filter(user=user, p_known__lt=0.6)
        .select_related("subsection__section__curriculum")
        .order_by("p_known")[:12]
    ):
        bonus, _ = skill_bonus(m.subsection)
        if bonus < 0:
            continue
        sub = m.subsection
        add(
            "practice",
            70 + (0.6 - m.p_known) * 40 + bonus,
            sub.title,
            f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}/practice",
            "weak",
            pct=int(m.p_known * 100),
        )
    # Felt too hard → gentler practice
    for fb in LessonFeedback.objects.filter(
        user=user, difficulty="hard", updated_at__gte=timezone.now() - timedelta(days=21)
    ).select_related("subsection__section")[:3]:
        sub = fb.subsection
        add(
            "practice",
            74,
            sub.title,
            f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}/practice",
            "tooHard",
        )
    # Next lessons in courses that match followed skills
    done = set(
        UserSubsectionState.objects.filter(
            user=user, status=UserSubsectionState.Status.COMPLETED
        ).values_list("subsection_id", flat=True)
    )
    from apps.learning.access import viewable_curricula

    covered: set[str] = set()
    for cur in viewable_curricula(user).filter(status=Curriculum.Status.READY).order_by("-updated_at")[:20]:
        cslugs = match_skills(cur.skills or [cur.title], index)
        covered |= cslugs
        if cslugs & hidden:
            continue
        nxt = (
            Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
            .exclude(id__in=done)
            .order_by("section__order", "order")
            .first()
        )
        if nxt and (cslugs & set(followed)):
            add(
                "next",
                60 + (10 - min(10, followed.index(next(iter(cslugs & set(followed)))))),
                nxt.title,
                f"/learn/{cur.id}/lesson/{nxt.id}",
                "nextFollowed",
                course=cur.title,
            )
    # Followed skills with no course yet → start one
    names = {s.slug: s for s, _ in index}
    for i, slug in enumerate(followed):
        if slug not in covered and slug in names:
            add("start", 52 - i, names[slug].name, f"/learn?new={slug}", "startSkill", skill=names[slug].name)
    # Curated paths for followed skills
    joined = set(PathEnrollment.objects.filter(user=user).values_list("path_id", flat=True))
    for p in (
        CuratedPath.objects.filter(published=True, org__isnull=True, skills__slug__in=followed)
        .exclude(id__in=joined)
        .distinct()[:3]
    ):
        add("path", 40, p.title, f"/paths/{p.slug}", "pathMatch")
    best: dict[str, dict] = {}
    for r in out:  # one card per destination, highest score wins
        if r["link"] not in best or r["score"] > best[r["link"]]["score"]:
            best[r["link"]] = r
    return sorted(best.values(), key=lambda x: -x["score"])[:limit]
