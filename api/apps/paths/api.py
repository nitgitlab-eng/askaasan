from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from llm.base import LLMError

from .models import CareerPath, CuratedPath, PathEnrollment, Placement, RoleAssessment, Skill, UserSkill
from .services import recommend, skill_mastery, user_skill_rows

AI_DAILY = 200  # shares the learner's AI budget with grading


def _charge(user, max_tokens=None):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, "ai_grades", 1, AI_DAILY, max_tokens=max_tokens)  # weighted by call size (H5)
        return None
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)


def _lang(user):
    from apps.learning.services import content_language
    from llm.prompts.curriculum import LANG_RULE

    return LANG_RULE[content_language(user)]


# ── Skills ───────────────────────────────────────────────────────────


def _skills_out(user):
    rows = user_skill_rows(user)
    mastery = skill_mastery(user)
    out = []
    for s in Skill.objects.filter(active=True):
        us = rows.get(s.slug)
        out.append(
            {
                "slug": s.slug,
                "name": s.name,
                "name_ta": s.name_ta,
                "category": s.category,
                "followed": bool(us and us.followed),
                "hidden": bool(us and us.hidden),
                "order": us.order if us else 999,
                "self_rating": us.self_rating if us else 0,
                "assessed_level": us.assessed_level if us else 0,
                "mastery": mastery.get(s.slug),
            }
        )
    return out


class SkillPatch(serializers.Serializer):
    followed = serializers.BooleanField(required=False)
    hidden = serializers.BooleanField(required=False)
    self_rating = serializers.IntegerField(min_value=0, max_value=5, required=False)


@api_view(["GET"])
def skills(request):
    return Response(_skills_out(request.user))


@api_view(["POST"])
def skill_update(request, slug):
    skill = get_object_or_404(Skill, slug=slug, active=True)
    ser = SkillPatch(data=request.data)
    ser.is_valid(raise_exception=True)
    us, created = UserSkill.objects.get_or_create(user=request.user, skill=skill)
    d = ser.validated_data
    if d.get("followed") and created:
        us.order = UserSkill.objects.filter(user=request.user, followed=True).count()
    for k, v in d.items():
        setattr(us, k, v)
    if d.get("hidden"):
        us.followed = False
    if d.get("followed"):
        us.hidden = False
    us.save()
    return Response(_skills_out(request.user))


@api_view(["POST"])
def skills_reorder(request):
    slugs = [s for s in request.data.get("slugs", []) if isinstance(s, str)][:100]
    with transaction.atomic():
        for i, slug in enumerate(slugs):
            UserSkill.objects.filter(user=request.user, skill__slug=slug).update(order=i)
    return Response(_skills_out(request.user))


@api_view(["POST"])
def skills_bulk(request):
    """Onboarding: follow chosen skills with their self-ratings."""
    items = request.data.get("skills", [])
    by_slug = {
        s.slug: s
        for s in Skill.objects.filter(
            slug__in=[i.get("slug") for i in items if isinstance(i, dict)], active=True
        )
    }
    with transaction.atomic():
        for i, item in enumerate(items[:40]):
            s = by_slug.get(item.get("slug"))
            if not s:
                continue
            rating = item.get("self_rating", 0)
            rating = rating if isinstance(rating, int) and 0 <= rating <= 5 else 0
            UserSkill.objects.update_or_create(
                user=request.user,
                skill=s,
                defaults={"followed": True, "hidden": False, "order": i, "self_rating": rating},
            )
    return Response(_skills_out(request.user))


@api_view(["GET"])
def recommendations(request):
    return Response(recommend(request.user))


# ── Curated paths ────────────────────────────────────────────────────


def _visible_paths(user):
    from django.db.models import Q

    from apps.orgs.models import Membership

    org_ids = Membership.objects.filter(user=user).values_list("org_id", flat=True)
    return CuratedPath.objects.filter(published=True).filter(Q(org__isnull=True) | Q(org_id__in=org_ids))


def _path_out(p, user, detail=False):
    enr = PathEnrollment.objects.filter(user=user, path=p).first()
    out = {
        "slug": p.slug,
        "title": p.title,
        "title_ta": p.title_ta,
        "description": p.description,
        "emoji": p.emoji,
        "level": p.level,
        "steps_n": len(p.steps),
        "skills": list(p.skills.values_list("slug", flat=True)),
        "joined": bool(enr),
        "org": p.org.name if p.org_id else None,
    }
    if detail:
        from apps.learning.models import Curriculum, UserSubsectionState

        steps = []
        for i, st in enumerate(p.steps):
            cid = (enr.step_courses if enr else {}).get(str(i))
            cur = Curriculum.objects.filter(pk=cid, owner=user).first() if cid else None
            prog = None
            if cur:
                total = sum(s.subsections.count() for s in cur.sections.all())
                done = UserSubsectionState.objects.filter(
                    user=user, subsection__section__curriculum=cur, status="completed"
                ).count()
                prog = {"course_id": cur.id, "status": cur.status, "done": done, "total": total}
            steps.append({**st, "index": i, "course": prog})
        out["steps"] = steps
    return out


@api_view(["GET", "POST"])
def curated(request):
    if request.method == "POST":
        if not request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        d = request.data
        steps = [
            {
                "title": str(s.get("title", ""))[:140],
                "goal": str(s.get("goal", ""))[:300],
                "skill": str(s.get("skill", ""))[:60],
            }
            for s in d.get("steps", [])
            if isinstance(s, dict) and s.get("goal")
        ][:12]
        if not d.get("title") or not steps:
            return Response({"code": "invalid"}, status=status.HTTP_400_BAD_REQUEST)
        from django.utils.text import slugify

        base = slugify(d["title"])[:70] or "path"
        slug, n = base, 1
        while CuratedPath.objects.filter(slug=slug).exists():
            n += 1
            slug = f"{base}-{n}"
        p = CuratedPath.objects.create(
            slug=slug,
            title=str(d["title"])[:140],
            description=str(d.get("description", ""))[:400],
            emoji=str(d.get("emoji", "🧭"))[:8],
            level=d.get("level", "beginner"),
            steps=steps,
            created_by=request.user,
        )
        p.skills.set(Skill.objects.filter(slug__in=[s["skill"] for s in steps]))
        return Response(_path_out(p, request.user), status=status.HTTP_201_CREATED)
    return Response(
        [_path_out(p, request.user) for p in _visible_paths(request.user).prefetch_related("skills")]
    )


@api_view(["GET"])
def curated_detail(request, slug):
    return Response(
        _path_out(get_object_or_404(_visible_paths(request.user), slug=slug), request.user, detail=True)
    )


@api_view(["POST"])
def curated_join(request, slug):
    p = get_object_or_404(_visible_paths(request.user), slug=slug)
    PathEnrollment.objects.get_or_create(user=request.user, path=p)
    for s in p.skills.all():
        UserSkill.objects.update_or_create(
            user=request.user, skill=s, defaults={"followed": True, "hidden": False}
        )
    return Response(_path_out(p, request.user, detail=True))


@api_view(["POST"])
def curated_link_step(request, slug, index):
    """After the learner creates the course for a step (normal course flow), remember it on the path."""
    from apps.learning.models import Curriculum

    p = get_object_or_404(_visible_paths(request.user), slug=slug)
    enr = get_object_or_404(PathEnrollment, user=request.user, path=p)
    if not 0 <= index < len(p.steps):
        return Response(status=status.HTTP_404_NOT_FOUND)
    cid = str(request.data.get("curriculum_id") or "")
    if not cid.isdigit():
        return Response({"code": "bad_curriculum"}, status=status.HTTP_400_BAD_REQUEST)
    cur = get_object_or_404(Curriculum, pk=int(cid), owner=request.user)
    enr.step_courses = {**enr.step_courses, str(index): cur.id}
    enr.save(update_fields=["step_courses"])
    return Response(_path_out(p, request.user, detail=True))


# ── Careers & competency frameworks ──────────────────────────────────


def _visible_careers(user):
    from django.db.models import Q

    from apps.orgs.models import Membership

    org_ids = Membership.objects.filter(user=user).values_list("org_id", flat=True)
    return CareerPath.objects.filter(published=True).filter(Q(org__isnull=True) | Q(org_id__in=org_ids))


def _career_out(c, user, detail=False):
    out = {
        "slug": c.slug,
        "title": c.title,
        "title_ta": c.title_ta,
        "summary": c.summary,
        "emoji": c.emoji,
        "salary_band": c.salary_band,
        "outlook": c.outlook,
        "path": c.path.slug if c.path_id else None,
        "seniority": c.seniority,
    }
    if detail:
        rows = user_skill_rows(user)
        mastery = skill_mastery(user)
        skills = {s.slug: s for s in Skill.objects.filter(slug__in=[r["skill"] for r in c.requirements])}
        reqs = []
        for r in c.requirements:
            us = rows.get(r["skill"])
            m = mastery.get(r["skill"])
            level = (
                (us.assessed_level if us and us.assessed_level else 0)
                or (us.self_rating if us else 0)
                or (round(1 + m * 3) if m is not None else 0)
            )
            s = skills.get(r["skill"])
            reqs.append(
                {
                    "skill": r["skill"],
                    "name": s.name if s else r["skill"],
                    "name_ta": s.name_ta if s else "",
                    "required": r["level"],
                    "level": level,
                    "gap": max(0, r["level"] - level),
                }
            )
        last = RoleAssessment.objects.filter(user=user, career=c, completed_at__isnull=False).first()
        out.update(
            requirements=reqs,
            readiness=round(
                sum(min(x["level"], x["required"]) for x in reqs) / max(1, sum(x["required"] for x in reqs)),
                3,
            ),
            last_assessment=last.completed_at if last else None,
        )
        from .plan_api import ladder_out

        out["ladder"] = ladder_out(c, user)
    return out


@api_view(["GET"])
def careers(request):
    return Response([_career_out(c, request.user) for c in _visible_careers(request.user)])


@api_view(["GET"])
def career_detail(request, slug):
    return Response(
        _career_out(get_object_or_404(_visible_careers(request.user), slug=slug), request.user, detail=True)
    )


def _public_questions(qs):
    return [
        {"id": i, "skill": q["skill"], "prompt": q["prompt"], "options": q["options"]}
        for i, q in enumerate(qs)
    ]


@api_view(["POST"])
def career_assessment(request, slug):
    from llm.prompts.paths import ROLE_SYSTEM, QuizSet
    from llm.structured import complete_json_sync

    c = get_object_or_404(_visible_careers(request.user), slug=slug)
    if denied := _charge(request.user, max_tokens=5000):
        return denied
    names = {s.slug: s.name for s in Skill.objects.filter(slug__in=[r["skill"] for r in c.requirements])}
    listing = "\n".join(f"- {names.get(r['skill'], r['skill'])}" for r in c.requirements)
    try:
        out = complete_json_sync(
            "author",
            ROLE_SYSTEM.format(role=c.title, lang_rule=_lang(request.user)),
            f"Skills:\n{listing}",
            QuizSet,
            max_tokens=5000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    by_name = {v.casefold(): k for k, v in names.items()}
    qs = [
        {**q.model_dump(), "skill": by_name.get(q.skill.casefold(), q.skill)}
        for q in out.questions
        if len(q.options) >= 2 and 0 <= q.correct < len(q.options)
    ][:24]
    a = RoleAssessment.objects.create(user=request.user, career=c, questions=qs)
    return Response({"id": a.id, "questions": _public_questions(qs)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def career_assessment_submit(request, pk):
    a = get_object_or_404(RoleAssessment, pk=pk, user=request.user, completed_at__isnull=True)
    answers = request.data.get("answers", {}) or {}
    per: dict[str, list[int]] = {}
    for i, q in enumerate(a.questions):
        per.setdefault(q["skill"], []).append(1 if answers.get(str(i)) == q["correct"] else 0)
    rows = user_skill_rows(request.user)
    levels = {}
    req = {r["skill"]: r["level"] for r in a.career.requirements}
    for skill_slug, hits in per.items():
        quiz_level = 1 + round(sum(hits) / len(hits) * 3)  # 1..4 from the quiz
        selfr = rows[skill_slug].self_rating if skill_slug in rows else 0
        levels[skill_slug] = round((quiz_level * 2 + selfr) / 3) if selfr else quiz_level
    with transaction.atomic():
        for slug_, lv in levels.items():
            skill = Skill.objects.filter(slug=slug_).first()
            if not skill:
                continue
            us, _ = UserSkill.objects.get_or_create(user=request.user, skill=skill)
            us.assessed_level = lv
            if lv < req.get(slug_, 0):  # gap → follow it so recommendations close it
                us.followed, us.hidden = True, False
            us.save()
        a.levels, a.score, a.completed_at = (
            levels,
            round(sum(sum(v) for v in per.values()) / max(1, len(a.questions)), 3),
            timezone.now(),
        )
        a.save()
    reveal = [
        {"id": i, "correct": q["correct"], "explanation": q["explanation"]} for i, q in enumerate(a.questions)
    ]
    return Response(
        {
            "levels": levels,
            "score": a.score,
            "reveal": reveal,
            "career": _career_out(a.career, request.user, detail=True),
        }
    )


# ── Placement test (onboarding) ──────────────────────────────────────


@api_view(["POST"])
def placement(request):
    from llm.prompts.paths import PLACEMENT_SYSTEM, QuizSet
    from llm.structured import complete_json_sync

    goal = str(request.data.get("goal") or "").strip()[:300]
    if len(goal) < 3:
        return Response({"code": "goal_required"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, max_tokens=3000):
        return denied
    try:
        out = complete_json_sync(
            "author",
            PLACEMENT_SYSTEM.format(goal=goal, n=5, lang_rule=_lang(request.user)),
            f"Goal: {goal}",
            QuizSet,
            max_tokens=3000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    qs = [q.model_dump() for q in out.questions if len(q.options) >= 2 and 0 <= q.correct < len(q.options)][
        :6
    ]
    p = Placement.objects.create(user=request.user, goal=goal, questions=qs)
    return Response({"id": p.id, "questions": _public_questions(qs)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def placement_submit(request, pk):
    p = get_object_or_404(Placement, pk=pk, user=request.user, level="")
    answers = request.data.get("answers", {}) or {}
    weights = [max(1, min(3, int(q.get("difficulty", 1)))) for q in p.questions]
    got = sum(
        w
        for i, (q, w) in enumerate(zip(p.questions, weights, strict=True))
        if answers.get(str(i)) == q["correct"]
    )
    score = got / max(1, sum(weights))
    level = "beginner" if score < 0.4 else "intermediate" if score < 0.75 else "advanced"
    p.level, p.score = level, round(score, 3)
    p.save(update_fields=["level", "score"])
    prof = request.user.profile
    prof.level = level
    prof.save(update_fields=["level"])
    return Response({"level": level, "score": p.score})


# ── Smart onboarding interview ───────────────────────────────────────


@api_view(["POST"])
def onboarding_chat(request):
    """Kili interviews a new learner; each turn returns a reply and the profile understood so far."""
    from apps.accounts.preferences import upgrade
    from llm.prompts.paths import ONBOARD_SYSTEM, OnboardTurn
    from llm.structured import complete_json

    msgs = [
        m
        for m in request.data.get("messages", [])
        if isinstance(m, dict) and m.get("role") in ("user", "assistant")
    ][-14:]
    if sum(1 for m in msgs if m["role"] == "user") > 8:
        return Response({"code": "too_long"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, max_tokens=1200):
        return denied
    mascot_name = upgrade(request.user.preferences.data)["mascot"]["name"]
    # The learner's own name, cleaned (it's user text in the system prompt) so the AI never guesses one from a place.
    prof = getattr(request.user, "profile", None)
    name = (
        " ".join(str(getattr(prof, "display_name", "") or "").split())[:40].replace("{", "").replace("}", "")
    )
    name_rule = (
        f"The learner's name is {name}. Call them only by this name, never by a place or anything else they mention."
        if name
        else "You don't know the learner's name: don't guess one from places or other details they mention."
    )
    system = ONBOARD_SYSTEM.format(mascot=mascot_name, lang_rule=_lang(request.user), name_rule=name_rule)
    convo = (
        "\n".join(
            f"{'Learner' if m['role'] == 'user' else mascot_name}: {str(m.get('content', ''))[:600]}"
            for m in msgs
        )
        or "(conversation starts)"
    )
    import asyncio

    from llm.router import aclose, resolve
    from llm.usage import flush_usage

    provider, model = resolve("onboarding")

    async def run():
        try:
            return await complete_json(
                provider,
                model,
                system,
                f"Conversation so far:\n{convo}\n\nYour next turn:",
                OnboardTurn,
                max_tokens=1200,
            )
        finally:
            await aclose(provider)

    try:
        from llm.dbconn import release_db

        release_db()
        out = asyncio.run(run())
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    finally:
        flush_usage(provider)
    return Response(out.model_dump())


@api_view(["POST"])
def onboarding_apply(request):
    """Save what the interview learned: goals, interests (→ followed skills), daily minutes, level."""
    from apps.accounts.serializers import validate_preferences_patch

    from .services import match_skills

    d = request.data.get("profile") or {}
    prof = request.user.profile
    if isinstance(d.get("goals"), list):
        prof.goals = [str(g)[:200] for g in d["goals"]][:5]
    if (
        d.get("level_guess") in ("beginner", "intermediate", "advanced")
        and not Placement.objects.filter(user=request.user).exclude(level="").exists()
    ):
        prof.level = d["level_guess"]
    prof.save()
    mins = d.get("minutes_per_day")
    if isinstance(mins, int) and 5 <= mins <= 240:
        prefs = request.user.preferences
        prefs.data = validate_preferences_patch(prefs.data, {"learning": {"daily_goal_minutes": mins}})
        prefs.save(update_fields=["data", "updated_at"])
    for i, slug in enumerate(sorted(match_skills([*d.get("interests", []), *d.get("goals", [])]))[:8]):
        skill = Skill.objects.filter(slug=slug).first()
        if skill:
            UserSkill.objects.update_or_create(
                user=request.user, skill=skill, defaults={"followed": True, "hidden": False, "order": i}
            )
    return Response({"ok": True})
