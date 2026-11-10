from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AnswerFeedback, Message

REASONS = ["wrong", "unclear", "too_long", "unsafe", "other"]


class FeedbackIn(serializers.Serializer):
    rating = serializers.ChoiceField(choices=[1, -1, 0])  # 0 = remove my rating
    reason = serializers.ChoiceField(choices=REASONS, required=False, allow_blank=True)
    comment = serializers.CharField(max_length=500, required=False, allow_blank=True)


def _target(user, kind, pk):
    """Only the learner who received the answer may rate it."""
    if kind == "message":
        m = get_object_or_404(Message, pk=pk, role=Message.Role.ASSISTANT, conversation__user=user)
        return m.content, m.model
    if kind == "live":
        from apps.live.models import LiveTurn

        t = get_object_or_404(LiveTurn, pk=pk, role="assistant", session__user=user)
        return t.text, "vision"
    if kind == "roleplay":
        from apps.roleplay.models import RolePlayTurn

        t = get_object_or_404(RolePlayTurn, pk=pk, role=RolePlayTurn.Role.CHARACTER, session__user=user)
        return t.text, "tutor"
    return None


@api_view(["POST"])
def rate(request, kind, pk):
    if kind not in AnswerFeedback.KINDS:
        return Response(status=status.HTTP_404_NOT_FOUND)
    ser = FeedbackIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    text, model = _target(request.user, kind, pk)
    if d["rating"] == 0:
        AnswerFeedback.objects.filter(user=request.user, kind=kind, object_id=pk).delete()
        return Response({"rating": 0})
    AnswerFeedback.objects.update_or_create(
        user=request.user,
        kind=kind,
        object_id=pk,
        defaults={
            "rating": d["rating"],
            "reason": d.get("reason", "") if d["rating"] < 0 else "",
            "comment": d.get("comment", ""),
            "model": model[:64],
            "excerpt": text[:300],
        },
    )
    return Response({"rating": d["rating"]})
