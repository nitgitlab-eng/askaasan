from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from llm.base import LLMError

from . import services
from .library import ensure_library
from .models import RolePlaySession, Scenario


def _visible_scenarios(user):
    ensure_library()
    return Scenario.objects.filter(Q(source="library") | Q(owner=user))


def _scenario_out(s):
    return {
        "id": s.id,
        "source": s.source,
        "emoji": s.emoji,
        "title": s.title,
        "summary": s.summary,
        "learner_role": s.learner_role,
        "character": {"name": s.character["name"], "persona": s.character["persona"]},
        "setting": s.setting,
        "objectives": s.objectives,
        "competencies": s.competencies,
        "difficulty": s.difficulty,
        "max_turns": s.max_turns,
    }


@api_view(["GET"])
def scenarios(request):
    return Response(
        [_scenario_out(s) for s in _visible_scenarios(request.user).order_by("source", "-created_at")[:60]]
    )


class Generate(serializers.Serializer):
    goal = serializers.CharField(min_length=5, max_length=300)
    difficulty = serializers.ChoiceField(choices=["easy", "medium", "hard"], default="medium")


@api_view(["POST"])
def generate(request):
    ser = Generate(data=request.data)
    ser.is_valid(raise_exception=True)
    if Scenario.objects.filter(owner=request.user).count() >= 50:
        return Response({"code": "too_many_scenarios"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if denied := _ai_budget(request.user):
        return denied
    try:
        sc = services.generate_scenario(
            request.user, ser.validated_data["goal"], ser.validated_data["difficulty"]
        )
    except services.NotAllowed:
        return Response({"code": "not_allowed"}, status=status.HTTP_400_BAD_REQUEST)
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response(_scenario_out(sc), status=status.HTTP_201_CREATED)


def _ai_budget(user):
    from apps.providers.services import BudgetExceeded

    try:
        services.charge_ai(user)
        return None
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)


@api_view(["DELETE"])
def scenario_detail(request, pk):
    get_object_or_404(Scenario, pk=pk, owner=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


def _session_out(s, turns=True):
    out = {
        "id": s.id,
        "status": s.status,
        "scenario": _scenario_out(s.scenario),
        "result": s.result,
        "started_at": s.started_at,
        "learner_turns": s.learner_turns,
        "lesson": None,
    }
    if s.activity_id and s.activity:
        sub = s.activity.subsection
        out["lesson"] = {
            "url": f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}",
            "title": sub.title,
            "activity_id": s.activity_id,
        }
    if turns:
        out["turns"] = [{"id": t.id, "role": t.role, "text": t.text} for t in s.turns.all()]
    return out


@api_view(["GET", "POST"])
def sessions(request):
    if request.method == "GET":
        qs = RolePlaySession.objects.filter(user=request.user).select_related("scenario")[:30]
        return Response([_session_out(s, turns=False) for s in qs])
    from apps.orgs.extras import refusal_response

    if denied := refusal_response(request.user, "roleplay"):
        return denied
    from apps.orgs.api import learner_assignments

    mine = learner_assignments(request.user).filter(scenario__isnull=False)
    from apps.journeys.services import journey_scenario_ids

    sc = get_object_or_404(
        _visible_scenarios(request.user)
        | Scenario.objects.filter(id__in=mine.values("scenario_id"))
        | Scenario.objects.filter(id__in=journey_scenario_ids(request.user)),
        pk=request.data.get("scenario_id"),
    )
    # Link the attempt to one assignment (the one the learner opened, else their newest for this scenario) so a library
    # scenario assigned by two orgs is never counted in both.
    mine = mine.filter(scenario=sc).order_by("-created_at")
    aid = str(request.data.get("assignment_id") or "")
    assignment = (mine.filter(pk=int(aid)).first() if aid.isdigit() else None) or mine.first()
    return Response(
        _session_out(services.start_session(request.user, sc, assignment=assignment)),
        status=status.HTTP_201_CREATED,
    )


def _feedback_survey(s):
    """An org's end-of-training survey for an assigned scenario the learner just finished (teacher tools, M9)."""
    from apps.orgs.teach import feedback_survey_for

    if s.status != RolePlaySession.Status.COMPLETED or not s.assignment_id:
        return None
    return feedback_survey_for(s.user, scenario_id=s.scenario_id, assignment_id=s.assignment_id)


@api_view(["GET"])
def session_detail(request, pk):
    s = get_object_or_404(RolePlaySession, pk=pk, user=request.user)
    from .coach import state

    return Response({**_session_out(s), "feedback_survey": _feedback_survey(s), "coach": state(s)})


@api_view(["POST"])
def session_end(request, pk):
    s = get_object_or_404(RolePlaySession, pk=pk, user=request.user)
    if s.status == RolePlaySession.Status.COMPLETED:
        return Response({"result": s.result, "reward": None})
    if s.learner_turns < services.MIN_TURNS_FOR_EVAL:
        return Response(
            {"code": "too_short", "min_turns": services.MIN_TURNS_FOR_EVAL},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if denied := _ai_budget(request.user):
        return denied
    # Claim the session atomically so two concurrent ends can't both pay for an evaluation.
    if not RolePlaySession.objects.filter(pk=s.pk, status=RolePlaySession.Status.ACTIVE).update(
        status=RolePlaySession.Status.EVALUATING
    ):
        return Response({"code": "evaluating"}, status=status.HTTP_409_CONFLICT)
    s.status = RolePlaySession.Status.EVALUATING
    try:
        result, reward = services.finish(s)
    except LLMError as e:
        s.status = RolePlaySession.Status.ACTIVE
        s.save(update_fields=["status"])
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception:  # don't strand the session in EVALUATING
        RolePlaySession.objects.filter(pk=s.pk).update(status=RolePlaySession.Status.ACTIVE)
        raise
    return Response({"result": result, "reward": reward, "feedback_survey": _feedback_survey(s)})


# ── Live coach (M10 rpx): tracker + fact checks + Kili's hints ───────


def _coach_session(request, pk):
    """The learner's own session; None + error response when the school switched role-play off."""
    from apps.orgs.extras import refusal_response

    s = get_object_or_404(
        RolePlaySession.objects.select_related("scenario", "user"), pk=pk, user=request.user
    )
    if denied := refusal_response(request.user, "roleplay"):
        return None, denied
    return s, None


def _coach_call(fn):
    from apps.providers.services import BudgetExceeded

    try:
        return fn(), None
    except BudgetExceeded:
        return None, Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except LLMError as e:
        return None, Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


@api_view(["GET", "POST"])
def session_coach(request, pk):
    """GET → live tracker state. POST → score the learner's latest turn (once per turn), then return the state."""
    from . import coach

    s, denied = _coach_session(request, pk)
    if denied:
        return denied
    if request.method == "POST" and s.status == RolePlaySession.Status.ACTIVE:
        _, err = _coach_call(lambda: coach.track_latest(s))
        if err:
            return err
    return Response(coach.state(s))


@api_view(["POST"])
def session_hint(request, pk):
    """Kili's private hint: limited per session, never added to the character's transcript."""
    from . import coach

    s, denied = _coach_session(request, pk)
    if denied:
        return denied
    if s.status != RolePlaySession.Status.ACTIVE:
        return Response({"code": "not_active"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        hint, err = _coach_call(lambda: coach.give_hint(s))
    except coach.HintLimit:
        return Response(
            {"code": "hint_limit", "limit": coach.HINTS_PER_SESSION}, status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    if err:
        return err
    return Response(
        {
            "hint": hint,
            "hints_used": len(s.hints),
            "hints_left": max(0, coach.HINTS_PER_SESSION - len(s.hints)),
        }
    )
