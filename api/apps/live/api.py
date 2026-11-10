from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import LiveSession
from .services import summarise


def _card(s: LiveSession) -> dict:
    return {
        "id": s.id,
        "topic": s.topic,
        "mode": s.mode,
        "started_at": s.started_at,
        "minutes": round(s.seconds / 60, 1),
        "frames": s.frames,
        "title": (s.summary or {}).get("title") or s.topic,
    }


@api_view(["GET"])
def sessions(request):
    return Response([_card(s) for s in LiveSession.objects.filter(user=request.user)[:30]])


@api_view(["GET", "POST"])
def session_detail(request, pk):
    s = get_object_or_404(LiveSession, pk=pk, user=request.user)
    if request.method == "POST":
        summarise(s)
    return Response(
        {
            **_card(s),
            "summary": s.summary,
            "turns": [
                {
                    "role": t.role,
                    "text": t.text,
                    "saw": t.saw_frame,
                    "proactive": t.proactive,
                    "at": t.created_at,
                }
                for t in s.turns.all()
            ],
        }
    )
