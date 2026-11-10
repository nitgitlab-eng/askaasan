"""Adaptive learning API.

Goal interview (a learner may know only a topic):
  POST goals/                     {topic, about?}            → scenario cards (3 real uses + 1 foundations track)
  POST goals/<id>/choose/         {index} | {custom}         → pick a card, or have their own use case checked
  POST goals/<id>/constraints/    {prior[], no_code, hours_week, deadline_weeks, level?}
  GET  goals/<id>/
Then POST /api/learn/curriculums/ with {goal_id} builds the course from the chosen scenario.

Per course:
  GET  courses/<id>/path/         the learner's own path (created on first visit)
  GET  courses/<id>/skill-map/    concepts with mastery"""

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.learning.access import get_viewable_curriculum
from llm.base import LLMError
from llm.fence import fence

from . import services
from .models import LearningGoal

AI_DAILY = 200  # shares the learner's daily AI budget with grading, like the onboarding interview


def _goal_ai_cap() -> int:
    return int(getattr(settings, "ADAPTIVE_GOAL_AI_CALLS", 4))


def _charge(user, goal: LearningGoal | None = None):
    from apps.providers.services import BudgetExceeded, charge

    if goal and goal.ai_calls >= _goal_ai_cap():
        return Response({"code": "goal_ai_limit"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        charge(user, "ai_grades", 1, AI_DAILY, max_tokens=1500)
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    return None


def _lang_rule(user) -> str:
    from apps.learning.services import content_language
    from llm.prompts.curriculum import LANG_RULE

    return LANG_RULE[content_language(user)]


def _about(user, typed: str) -> str:
    if typed:
        return typed
    from apps.study.about import context_line

    return context_line(user)


def _clean(s) -> dict:
    return {
        "title": s.title.strip()[:120],
        "deliverable": s.deliverable.strip()[:300],
        "level": s.level if s.level in ("beginner", "intermediate", "advanced") else "beginner",
        "weeks": max(1, min(8, int(s.weeks or 3))),
        "foundations": bool(s.foundations),
    }


def goal_out(g: LearningGoal) -> dict:
    return {
        "id": g.id,
        "topic": g.topic,
        "about": g.about,
        "status": g.status,
        "suggestions": g.suggestions,
        "scenario": g.scenario,
        "prior": g.prior,
        "constraints": g.constraints,
        "level": g.level,
        "curriculum_id": g.curriculum_id,
        "ai_left": max(0, _goal_ai_cap() - g.ai_calls),
    }


class GoalIn(serializers.Serializer):
    topic = serializers.CharField(max_length=200, min_length=2)
    about = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


@api_view(["POST"])
def goals(request):
    from llm.prompts.adaptive import SUGGEST_SYSTEM, ScenarioSet
    from llm.structured import complete_json_sync

    ser = GoalIn(data=request.data)
    ser.is_valid(raise_exception=True)
    topic, about = ser.validated_data["topic"].strip(), ser.validated_data["about"].strip()
    if denied := _charge(request.user):
        return denied
    try:
        out = complete_json_sync(
            "adaptive_interview",
            SUGGEST_SYSTEM.format(lang_rule=_lang_rule(request.user)),
            f"{fence('topic', topic)}\n{fence('about', _about(request.user, about) or 'unknown')}",
            ScenarioSet,
            max_tokens=1500,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    cards = [_clean(s) for s in out.scenarios if s.title.strip()]
    real = [c for c in cards if not c["foundations"]][:3]
    base = next((c for c in cards if c["foundations"]), None) or {
        "title": f"Learn the basics of {topic}"[:120],
        "deliverable": f"Understand the core ideas of {topic} and where they are used."[:300],
        "level": "beginner",
        "weeks": 3,
        "foundations": True,
    }
    g = LearningGoal.objects.create(
        user=request.user, topic=topic, about=about, suggestions=[*real, base], ai_calls=1
    )
    return Response(goal_out(g), status=status.HTTP_201_CREATED)


def _own_goal(request, pk) -> LearningGoal:
    return get_object_or_404(LearningGoal, pk=pk, user=request.user)


@api_view(["GET"])
def goal_detail(request, pk):
    return Response(goal_out(_own_goal(request, pk)))


@api_view(["POST"])
def goal_choose(request, pk):
    """{index}: pick one of the cards. {custom}: the learner's own use case, checked by AI first
    (accept → chosen; split/decline → new cards to pick from, with a reason)."""
    from llm.prompts.adaptive import VERIFY_SYSTEM, Verdict
    from llm.structured import complete_json_sync

    g = _own_goal(request, pk)
    if g.status == LearningGoal.Status.USED:
        return Response({"code": "goal_used"}, status=status.HTTP_409_CONFLICT)
    index = request.data.get("index")
    if isinstance(index, int) and not isinstance(index, bool):
        if not 0 <= index < len(g.suggestions):
            return Response({"code": "bad_index"}, status=status.HTTP_400_BAD_REQUEST)
        g.scenario = {**g.suggestions[index], "custom": False}
        g.level = g.scenario["level"]
        g.status = LearningGoal.Status.CHOSEN
        g.save()
        return Response({**goal_out(g), "verdict": "chosen"})
    custom = str(request.data.get("custom") or "").strip()[:300]
    if len(custom) < 4:
        return Response({"code": "custom_required"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, g):
        return denied
    try:
        v = complete_json_sync(
            "adaptive_interview",
            VERIFY_SYSTEM.format(lang_rule=_lang_rule(request.user)),
            f"{fence('use_case', custom)}\n{fence('topic', g.topic)}\n"
            f"{fence('about', _about(request.user, g.about) or 'unknown')}",
            Verdict,
            max_tokens=1500,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    g.ai_calls += 1
    verdict = v.verdict if v.verdict in ("accept", "split", "decline") else "decline"
    reason = v.reason.strip()[:300]
    if verdict == "accept":
        g.scenario = {**_clean(v.scenario), "foundations": False, "custom": True, "asked": custom}
        g.level = g.scenario["level"]
        g.status = LearningGoal.Status.CHOSEN
    else:
        alts = [{**_clean(s), "foundations": False} for s in v.alternatives if s.title.strip()][:3]
        foundations = [c for c in g.suggestions if c.get("foundations")][:1]
        g.suggestions = [*(alts or [{**_clean(v.scenario), "foundations": False}]), *foundations]
    g.save()
    return Response({**goal_out(g), "verdict": verdict, "reason": reason})


class ConstraintsIn(serializers.Serializer):
    prior = serializers.ListField(child=serializers.CharField(max_length=60), max_length=10, default=list)
    no_code = serializers.BooleanField(default=False)
    hours_week = serializers.IntegerField(min_value=1, max_value=40, default=3)
    deadline_weeks = serializers.IntegerField(min_value=1, max_value=52, required=False, allow_null=True)
    level = serializers.ChoiceField(choices=["beginner", "intermediate", "advanced"], required=False)


@api_view(["POST"])
def goal_constraints(request, pk):
    g = _own_goal(request, pk)
    if g.status not in (LearningGoal.Status.CHOSEN, LearningGoal.Status.READY):
        return Response({"code": "choose_first"}, status=status.HTTP_409_CONFLICT)
    ser = ConstraintsIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    g.prior = [p.strip() for p in d["prior"] if p.strip()]
    g.constraints = {
        "no_code": d["no_code"],
        "hours_week": d["hours_week"],
        "deadline_weeks": d.get("deadline_weeks"),
    }
    if d.get("level"):
        g.level = d["level"]
    g.status = LearningGoal.Status.READY
    g.save()
    return Response(goal_out(g))


def course_fields(g: LearningGoal) -> dict:
    """What the course generator gets from a ready goal (used by POST /api/learn/curriculums/ with goal_id)."""
    s = g.scenario
    notes = [
        f"Learner's real-life goal: {s.get('title', '')}. By the end they will: {s.get('deliverable', '')}"
    ]
    if g.about:
        notes.append(f"About them: {g.about}")
    if g.prior:
        notes.append(f"Already knows: {', '.join(g.prior)} (don't re-teach; build on it)")
    if g.constraints.get("no_code"):
        notes.append("They don't want to write code: use tools and no-code steps, no programming exercises.")
    if hw := g.constraints.get("hours_week"):
        notes.append(f"About {hw} hours a week.")
    notes.append(
        "Every lesson must move them toward that goal; skip theory they won't use."
        if not s.get("foundations")
        else "Teach the core ideas clearly with everyday examples."
    )
    return {
        "goal": (s.get("title") or g.topic)[:300],
        "level": g.level,
        "notes": " ".join(notes)[:1000],
    }


@api_view(["GET"])
def course_path(request, pk):
    cur = get_viewable_curriculum(request.user, pk)
    path = services.get_path(request.user, cur)
    if not path:
        return Response({"code": "course_not_ready"}, status=status.HTTP_409_CONFLICT)
    return Response(services.path_out(path))


@api_view(["GET"])
def course_skill_map(request, pk):
    cur = get_viewable_curriculum(request.user, pk)
    if not services.get_path(request.user, cur):
        return Response({"code": "course_not_ready"}, status=status.HTTP_409_CONFLICT)
    return Response(services.skill_map(request.user, cur))
