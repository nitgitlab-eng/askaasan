"""Career role ladder (current → next → senior roles) and the learner's "plan my next 30 days" competency plan."""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from llm.base import LLMError

from .models import CareerPlan, Skill

PLANS_PER_DAY = 5  # each generation / regeneration is charged against this daily allowance
GOALS_PER_WEEK = 4
PLAN_DAYS = 30


def _card(c) -> dict:
    return {
        "slug": c.slug,
        "title": c.title,
        "title_ta": c.title_ta,
        "emoji": c.emoji,
        "seniority": c.seniority,
    }


def ladder_out(c, user) -> dict:
    """Only roles the learner can see (public, or their org's own). Previous roles = roles that list this one as next."""
    from .api import _visible_careers

    vis = {x.slug: x for x in _visible_careers(user)}
    return {
        "current": _card(c),
        "previous": [_card(x) for x in vis.values() if c.slug in (x.next_roles or [])][:6],
        "next": [_card(vis[s]) for s in c.next_roles or [] if s in vis and s != c.slug],
        "senior": [_card(vis[s]) for s in c.senior_roles or [] if s in vis and s != c.slug],
    }


# ── 30-day plan ──────────────────────────────────────────────────────


def _courses(user):
    """Courses the learner can already open (own or enrolled), with a few lessons each — the plan may only point at these."""
    from apps.learning.access import viewable_curricula
    from apps.learning.models import Subsection

    curs = {c.id: c for c in viewable_curricula(user).filter(status="ready").order_by("-updated_at")[:25]}
    lessons: dict[int, dict[int, str]] = {}
    for sid, title, cid in (
        Subsection.objects.filter(
            section__curriculum_id__in=list(curs), archived=False, section__archived=False
        )
        .order_by("section__order", "order")
        .values_list("id", "title", "section__curriculum_id")
    ):
        if len(lessons.setdefault(cid, {})) < 8:
            lessons[cid][sid] = title
    return curs, lessons


def week_bounds(start, week: int):
    a = start + timedelta(days=7 * (week - 1))
    return a, (start + timedelta(days=PLAN_DAYS - 1)) if week == 4 else a + timedelta(days=6)


def build_plan(out, start, reqs, curs, lessons) -> dict:
    """Validate the AI's plan: weeks 1-4, known skills, real course/lesson ids (else a new-course goal), dated goals."""
    skills = {s.slug: s.name for s in Skill.objects.all()}
    by_gap = [r["skill"] for r in sorted(reqs, key=lambda r: -r["gap"])] or list(skills)[:1]
    themes = {w.week: w.theme[:80] for w in out.weeks if 1 <= w.week <= 4}
    per_week: dict[int, list] = {w: [] for w in range(1, 5)}
    for g in out.goals:
        if not 1 <= g.week <= 4 or len(per_week[g.week]) >= GOALS_PER_WEEK or not g.title.strip():
            continue
        skill = g.skill if g.skill in skills else (by_gap[0] if by_gap else "")
        cid = g.course_id if g.course_id in curs else 0
        lid = g.lesson_id if cid and g.lesson_id in lessons.get(cid, {}) else 0
        per_week[g.week].append(
            {
                "title": g.title.strip()[:160],
                "skill": skill,
                "skill_name": skills.get(skill, ""),
                "course_id": cid or None,
                "course_title": curs[cid].title if cid else "",
                "lesson_id": lid or None,
                "lesson_title": lessons[cid][lid] if lid else "",
                "course_goal": "" if cid else (g.course_goal.strip() or g.title.strip())[:200],
            }
        )
    weeks, goals = [], []
    for w in range(1, 5):
        a, b = week_bounds(start, w)
        weeks.append(
            {"week": w, "theme": themes.get(w) or f"Week {w}", "start": a.isoformat(), "end": b.isoformat()}
        )
        rows = per_week[w]
        span = (b - a).days + 1
        for k, g in enumerate(
            rows
        ):  # spread the week's goals evenly, the last one due on the week's last day
            due = a + timedelta(days=max(0, round((k + 1) * span / len(rows)) - 1))
            goals.append(
                {
                    "id": f"g{len(goals) + 1}",
                    "week": w,
                    "order": k,
                    "due": due.isoformat(),
                    "done": False,
                    **g,
                }
            )
    people = [
        {"role": p.role.strip()[:120], "why": p.why.strip()[:240], "ask": p.ask.strip()[:240]}
        for p in out.people
        if p.role.strip()
    ][:5]
    return {"summary": out.summary.strip()[:400], "weeks": weeks, "goals": goals, "people": people}


def plan_out(p: CareerPlan | None, user) -> dict | None:
    if not p:
        return None
    from apps.learning.access import viewable_curricula

    ids = {g["course_id"] for g in p.goals if g.get("course_id")}
    open_ids = set(viewable_curricula(user).filter(id__in=ids).values_list("id", flat=True)) if ids else set()
    weeks = []
    for w in p.weeks:
        rows = []
        for g in p.goals:
            if g["week"] != w["week"]:
                continue
            cid = g.get("course_id")
            link = (
                (f"/learn/{cid}/lesson/{g['lesson_id']}" if g.get("lesson_id") else f"/learn/{cid}")
                if cid in open_ids
                else ""
            )
            rows.append({**g, "link": link})
        weeks.append({**w, "goals": rows})
    return {
        "career": p.career.slug,
        "start_date": p.start_date,
        "end_date": p.start_date + timedelta(days=PLAN_DAYS - 1),
        "summary": p.summary,
        "weeks": weeks,
        "people": p.people,
        "generations": p.generations,
        "updated_at": p.updated_at,
        "done": sum(1 for g in p.goals if g.get("done")),
        "total": len(p.goals),
    }


@api_view(["GET", "POST"])
def career_plan(request, slug):
    from apps.providers.services import BudgetExceeded, charge
    from llm.prompts.journeys import CAREER_PLAN_SYSTEM
    from llm.prompts.journeys import CareerPlan as PlanSchema
    from llm.structured import complete_json_sync

    from .api import _career_out, _lang, _visible_careers

    c = get_object_or_404(_visible_careers(request.user), slug=slug)
    existing = CareerPlan.objects.filter(user=request.user, career=c).select_related("career").first()
    if request.method == "GET":
        return Response({"plan": plan_out(existing, request.user)})
    reqs = _career_out(c, request.user, detail=True)["requirements"]
    curs, lessons = _courses(request.user)
    try:
        charge(request.user, "career_plan", 1, PLANS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    lad = ladder_out(c, request.user)
    listing = "\n".join(
        [
            "SKILLS (slug: current level → required):",
            *[f"- {r['skill']} ({r['name']}): {r['level']} → {r['required']}" for r in reqs],
            "NEXT ROLES: " + ", ".join(x["title"] for x in lad["next"] + lad["senior"]),
            "COURSES (id: title; lessons id: title):",
            *[
                f"- {cid}: {cur.title[:90]}; "
                + "; ".join(f"{sid}: {t[:60]}" for sid, t in lessons.get(cid, {}).items())
                for cid, cur in curs.items()
            ],
        ]
    )
    try:
        out = complete_json_sync(
            "suggest",
            CAREER_PLAN_SYSTEM.format(role=c.title, lang_rule=_lang(request.user)),
            listing,
            PlanSchema,
            max_tokens=4000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    start = timezone.localdate()
    data = build_plan(out, start, reqs, curs, lessons)
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        existing.start_date, existing.generations = start, existing.generations + 1
        existing.save()
        p = existing
    else:
        p = CareerPlan.objects.create(user=request.user, career=c, start_date=start, **data)
    return Response({"plan": plan_out(p, request.user)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def career_plan_goal(request, slug, gid):
    """Tick a goal off (done: bool), or link the new AI course the learner just created for it (course_id)."""
    from apps.learning.models import Curriculum

    p = get_object_or_404(CareerPlan.objects.select_related("career"), user=request.user, career__slug=slug)
    goal = next((g for g in p.goals if g.get("id") == gid), None)
    if not goal:
        return Response(status=status.HTTP_404_NOT_FOUND)
    if "done" in request.data:
        if not isinstance(request.data.get("done"), bool):
            return Response({"code": "bad_value"}, status=status.HTTP_400_BAD_REQUEST)
        goal["done"] = request.data["done"]
    if request.data.get("course_id"):
        if not str(request.data.get("course_id")).isdigit():
            return Response({"code": "bad_value"}, status=status.HTTP_400_BAD_REQUEST)
        cur = get_object_or_404(
            Curriculum, pk=int(request.data["course_id"]), owner=request.user
        )  # only the learner's own course
        goal.update(course_id=cur.id, course_title=cur.title[:200], lesson_id=None, lesson_title="")
    p.save(update_fields=["goals", "updated_at"])
    return Response({"plan": plan_out(p, request.user)})
