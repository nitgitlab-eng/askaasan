"""Mid-lesson pulse check: pace / difficulty / energy / relevance → Kili adapts right away, and later lessons adapt too."""

from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import PulseCheck


class PulseIn(serializers.Serializer):
    pace = serializers.ChoiceField(choices=["slow", "ok", "fast"], required=False)
    difficulty = serializers.ChoiceField(choices=["easy", "right", "hard"], required=False)
    energy = serializers.ChoiceField(choices=["low", "ok", "high"], required=False)
    relevant = serializers.BooleanField(required=False, allow_null=True)
    wish = serializers.CharField(max_length=300, required=False, allow_blank=True)
    lang = serializers.CharField(max_length=10, required=False, allow_blank=True)


@api_view(["POST"])
def pulse(request, pk):
    from apps.learning.access import get_viewable_subsection
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.study import PULSE_SYSTEM, PulseReply
    from llm.structured import complete_json_sync

    from .assist import _ai_charge, _lang_code

    sub = get_viewable_subsection(request.user, pk)
    ser = PulseIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    lang = _lang_code(request.user, d.pop("lang", None), sub.section.curriculum.language)
    pc = PulseCheck.objects.create(user=request.user, subsection=sub, **d)
    if denied := _ai_charge(request.user):
        return denied
    struggling = pc.pace == "fast" or pc.difficulty == "hard"
    stretch = pc.pace == "slow" or pc.difficulty == "easy" or pc.relevant is False
    brief = (
        f"Lesson: {sub.title}\nObjective: {sub.objective}\n\n{sub.explanation_md[:5000]}\n\n"
        f"Learner says — pace: {pc.pace or '-'} (fast = too fast for them), difficulty: {pc.difficulty or '-'}, energy: {pc.energy or '-'}, "
        f"covers what they wanted: {'-' if pc.relevant is None else ('yes' if pc.relevant else 'no')}, hoped to learn: {pc.wish or '-'}\n"
        f"Needs simpler: {struggling}. Wants more: {stretch}."
    )
    try:
        from apps.accounts.companion import as_companion

        system = as_companion(
            PULSE_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])), request.user
        )
        out = complete_json_sync("tutor", system, brief, PulseReply, max_tokens=1500)
    except Exception:  # noqa: BLE001 — the check-in is saved either way
        return Response(
            {"saved": True, "message": "", "tip": "", "simpler": "", "extra": ""},
            status=status.HTTP_201_CREATED,
        )
    return Response(
        {
            "saved": True,
            "message": out.message,
            "tip": out.tip,
            "simpler": out.simpler if struggling else "",
            "extra": out.extra if stretch else "",
        },
        status=status.HTTP_201_CREATED,
    )


def recent_feel(user, curriculum) -> str:
    """One line for lesson generation: how this learner's recent check-ins in the course went."""
    rows = list(
        PulseCheck.objects.filter(user=user, subsection__section__curriculum=curriculum).order_by(
            "-created_at"
        )[:5]
    )
    if not rows:
        return ""
    hard = sum(r.difficulty == "hard" or r.pace == "fast" for r in rows)
    easy = sum(r.difficulty == "easy" or r.pace == "slow" for r in rows)
    wishes = "; ".join(r.wish for r in rows if r.wish)[:300]
    tone = (
        "They found recent lessons too hard/fast — go simpler, shorter steps, more examples."
        if hard > easy
        else "They found recent lessons too easy/slow — go a bit deeper and faster."
        if easy > hard
        else ""
    )
    return " ".join(x for x in (tone, f"They hoped to learn: {wishes}." if wishes else "") if x)
