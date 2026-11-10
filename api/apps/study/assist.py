"""B1: Kili's hint ladder (nudge → hint → worked example) and 'explain this' on selected lesson text."""

import json

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.accounts.companion import DEFAULT_NAMES, PERSONA, as_companion, companion

from .models import LANGS, ActivityHint, HintUse

HINT_COST = {1: 0, 2: 2, 3: 5}  # coins: the first nudge is free
HINT_WORDS = {1: 40, 2: 90, 3: 220}
AI_DAILY = 200


def _lang_code(user, requested: str | None, cur_lang: str) -> str:
    from apps.learning.services import content_language

    if requested in LANGS or requested == "tanglish":
        return requested
    return cur_lang or content_language(user)


def _ai_charge(user, max_tokens=None):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, "ai_grades", 1, AI_DAILY, max_tokens=max_tokens)  # weighted by call size (H5)
        return None
    except BudgetExceeded:
        return Response({"code": "ai_budget_exceeded"}, status=status.HTTP_429_TOO_MANY_REQUESTS)


def _hint_voice(system: str, user) -> tuple[str, str]:
    """(character, system prompt) for a shared, cached hint: the learner's chosen character with its *default* name
    and persona, so one learner's free-text companion name never reaches text other learners are served."""
    ch = companion(user)["character"]
    name = DEFAULT_NAMES[ch]
    return ch, system.replace("You are Kili, ", f"You are {name}, {PERSONA[ch]} — ", 1).replace("Kili", name)


@api_view(["POST"])
def activity_hint(request, pk):
    """POST {level: 1|2|3, lang?} → {level, text, cost, coins}. Levels unlock in order; repeats are free."""
    from apps.game.models import XPEvent
    from apps.game.services import stats_for
    from apps.learning.access import get_viewable_activity
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import HINT_SYSTEM, HintOut
    from llm.structured import complete_json_sync

    activity = get_viewable_activity(request.user, pk)
    try:
        level = int(request.data.get("level", 1))
    except (TypeError, ValueError):
        level = 0
    if level not in HINT_COST:
        return Response({"code": "bad_level"}, status=status.HTTP_400_BAD_REQUEST)
    used = set(HintUse.objects.filter(user=request.user, activity=activity).values_list("level", flat=True))
    if level > 1 and (level - 1) not in used:
        return Response({"code": "previous_level_first"}, status=status.HTTP_400_BAD_REQUEST)
    lang = _lang_code(request.user, request.data.get("lang"), activity.subsection.section.curriculum.language)

    persona, system = _hint_voice(
        HINT_SYSTEM.format(
            level=level, words=HINT_WORDS[level], lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])
        ),
        request.user,
    )
    hint = ActivityHint.objects.filter(activity=activity, level=level, lang=lang, persona=persona).first()
    if not hint:
        if denied := _ai_charge(request.user, max_tokens=1200):
            return denied
        # The hint is cached for other learners, so the answer key never goes to the model: it can't leak what it never saw.
        material = {"type": activity.type, "title": activity.title, "payload": activity.payload}
        try:
            out = complete_json_sync(
                "tutor",
                system,
                f"Lesson: {activity.subsection.title}\nActivity:\n{json.dumps(material, ensure_ascii=False)[:6000]}",
                HintOut,
                max_tokens=1200,
            )
        except LLMError as e:
            return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        try:
            with transaction.atomic():
                hint = ActivityHint.objects.create(
                    activity=activity, level=level, lang=lang, persona=persona, text=out.text.strip()
                )
        except IntegrityError:  # another learner generated it at the same moment
            hint = ActivityHint.objects.get(activity=activity, level=level, lang=lang, persona=persona)

    cost = 0
    if level not in used:
        with transaction.atomic():
            s = stats_for(request.user)
            s = type(s).objects.select_for_update().get(pk=s.pk)
            # Re-check under the lock: a parallel request may have paid for this level while the LLM ran.
            if not HintUse.objects.filter(user=request.user, activity=activity, level=level).exists():
                cost = HINT_COST[level]
                if s.coins < cost:
                    return Response(
                        {"code": "not_enough_coins", "cost": cost, "coins": s.coins},
                        status=status.HTTP_402_PAYMENT_REQUIRED,
                    )
                s.coins -= cost
                s.save(update_fields=["coins"])
                HintUse.objects.create(user=request.user, activity=activity, level=level, cost=cost)
                if cost:
                    XPEvent.objects.create(
                        user=request.user,
                        kind="hint",
                        coins=-cost,
                        ref=f"hint:{activity.id}:{level}",
                        day=timezone.localdate(),
                    )
    coins = stats_for(request.user).coins
    return Response(
        {
            "level": level,
            "text": hint.text,
            "cost": cost,
            "coins": coins,
            "next_cost": HINT_COST.get(level + 1),
        }
    )


@api_view(["GET"])
def activity_hints_used(request, pk):
    from apps.learning.access import get_viewable_activity

    activity = get_viewable_activity(request.user, pk)
    used = sorted(
        HintUse.objects.filter(user=request.user, activity=activity).values_list("level", flat=True)
    )
    return Response({"used": used, "costs": HINT_COST})


@api_view(["POST"])
def explain(request):
    """POST {text, subsection_id, lang?} → {text}: a short explanation of highlighted lesson text."""
    from apps.learning.access import get_viewable_subsection
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import EXPLAIN_SYSTEM, Explained
    from llm.structured import complete_json_sync

    text = str(request.data.get("text") or "").strip()
    if not 2 <= len(text) <= 600:
        return Response({"code": "bad_text"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        sub_id = int(request.data.get("subsection_id"))
    except (TypeError, ValueError):
        return Response({"code": "bad_subsection"}, status=status.HTTP_400_BAD_REQUEST)
    sub = get_viewable_subsection(request.user, sub_id)
    lang = _lang_code(request.user, request.data.get("lang"), sub.section.curriculum.language)
    if denied := _ai_charge(request.user, max_tokens=800):
        return denied
    try:
        out = complete_json_sync(
            "tutor",
            as_companion(EXPLAIN_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])), request.user),
            f"Lesson: {sub.title}\nLesson text (context):\n{sub.explanation_md[:3000]}\n\nHighlighted: {text}",
            Explained,
            max_tokens=800,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return Response({"text": out.text.strip()})
