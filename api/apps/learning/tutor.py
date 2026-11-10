"""Learn with Kili: the lesson taught in a chat, one idea at a time, with a quick check after each.

The server owns the session (chunks, which one is being taught, mastery per chunk). The model only ever sees the
lesson's own text — never the activities or their answer keys — so it cannot leak them."""

import logging
import re

from django.db import IntegrityError, transaction
from rest_framework import serializers, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .access import get_viewable_subsection
from .models import TutorSession

log = logging.getLogger(__name__)

TUTOR_TURNS_PER_DAY = 80  # AI tutor turns per learner per day (cost guard)
PASS = 0.7
MAX_TRIES = 3  # check answers on one idea before moving on anyway (after two different re-explanations)
MAX_CHUNKS, MIN_CHARS = 5, 160
MAX_MESSAGES = 120


def chunk_lesson(md: str) -> list[dict]:
    """Split the explanation into 2-5 bite-size ideas along paragraph boundaries (no AI call needed)."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", md or "") if p.strip()]
    merged: list[str] = []
    for p in paras:
        if merged and (
            len(merged[-1]) < MIN_CHARS or re.match(r"^#{1,6}\s", merged[-1]) and "\n" not in merged[-1]
        ):
            merged[-1] = f"{merged[-1]}\n\n{p}"
        else:
            merged.append(p)
    while len(merged) > MAX_CHUNKS:  # join the shortest neighbouring pair
        i = min(range(len(merged) - 1), key=lambda k: len(merged[k]) + len(merged[k + 1]))
        merged[i : i + 2] = [f"{merged[i]}\n\n{merged[i + 1]}"]
    out = []
    for text in merged or [md.strip() or "…"]:
        head = re.match(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
        bold = re.search(r"\*\*(.+?)\*\*", text)
        title = (head.group(1) if head else bold.group(1) if bold else " ".join(text.split()[:6])).strip(
            " #*:"
        )[:80]
        out.append({"title": title, "text": text[:3000]})
    return out


def _lang(request, sub) -> str:
    from llm.prompts.curriculum import LANG_RULE

    lang = str(request.data.get("lang") or request.query_params.get("lang") or "")
    return lang if lang in LANG_RULE else sub.section.curriculum.language


def _state(s: TutorSession | None) -> dict:
    if not s:
        return {"status": "none"}
    return {
        "status": "done" if s.done else "active",
        "chunks": [{"title": c["title"], "mastery": s.mastery.get(str(i))} for i, c in enumerate(s.chunks)],
        "current": s.current,
        "total": len(s.chunks),
        "question": "" if s.done else s.question,
        "messages": s.messages[-MAX_MESSAGES:],
    }


def _charge(user):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, "lx_tutor_turns", 1, TUTOR_TURNS_PER_DAY)
    except BudgetExceeded:
        return Response({"code": "tutor_budget"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    return None


def _blocked(user):
    from apps.orgs.extras import refusal_response

    return refusal_response(user, "mentor")


def _brief(sub) -> str:
    from llm.prompts.lx import tutor_lesson_brief

    return tutor_lesson_brief(sub.section.curriculum.title, sub.title, sub.objective)


def teach(sub, chunks: list[dict], i: int, lang: str, learner=None):
    from llm.fence import fence
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.guardrails import guardrails
    from llm.prompts.lx import TUTOR_TEACH_SYSTEM, TutorTeach
    from llm.structured import complete_json_sync

    user = f"{_brief(sub)}\n\nIdea {i + 1} of {len(chunks)} — teach this now:\n{fence('idea', chunks[i]['text'])}"
    from apps.accounts.companion import as_companion

    system = as_companion(TUTOR_TEACH_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])), learner)
    system += guardrails(learner)
    return complete_json_sync("tutor", system, user, TutorTeach, max_tokens=1200)


def assess(sub, s: TutorSession, answer: str, lang: str, learner=None):
    from llm.fence import defang, fence
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.guardrails import guardrails
    from llm.prompts.lx import TUTOR_TURN_SYSTEM, TutorTurn
    from llm.structured import complete_json_sync

    i = s.current
    nxt = s.chunks[i + 1]["text"] if i + 1 < len(s.chunks) else ""
    user = (
        f"{_brief(sub)}\n\nCurrent idea ({i + 1} of {len(s.chunks)}):\n{fence('idea', s.chunks[i]['text'])}\n"
        f"Your check question: {s.question}\n"
        + (
            f"Next idea ({i + 2} of {len(s.chunks)}):\n{fence('next_idea', nxt)}\n"
            if nxt
            else "There is no next idea: wrap up.\n"
        )
        # the learner's text can't close its own fence or fake an <idea> block
        + fence("learner_answer", defang(answer, "idea", "next_idea"))
    )
    from apps.accounts.companion import as_companion

    system = as_companion(TUTOR_TURN_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])), learner)
    system += guardrails(learner)
    return complete_json_sync("tutor", system, user, TutorTurn, max_tokens=2000)


class StartIn(serializers.Serializer):
    restart = serializers.BooleanField(required=False, default=False)
    lang = serializers.CharField(max_length=12, required=False, allow_blank=True)


@api_view(["GET", "POST", "DELETE"])
def tutor(request, pk):
    """GET: my session for this lesson. POST: start (or resume; restart=true begins again). DELETE: forget it."""
    sub = get_viewable_subsection(request.user, pk)
    s = TutorSession.objects.filter(user=request.user, subsection=sub).first()
    if request.method == "GET":
        return Response(_state(s))
    if request.method == "DELETE":
        if s:
            s.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if denied := _blocked(request.user):
        return denied
    ser = StartIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if s and not ser.validated_data["restart"]:
        return Response(_state(s))
    if sub.lesson_status != "ready" or not sub.explanation_md.strip():
        return Response({"code": "lesson_not_ready"}, status=status.HTTP_409_CONFLICT)
    if denied := _charge(request.user):
        return denied
    chunks = chunk_lesson(sub.explanation_md)
    try:
        first = teach(sub, chunks, 0, _lang(request, sub), request.user)
    except Exception:
        log.exception("tutor start failed for lesson %s", sub.id)
        return Response({"code": "tutor_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    fields = {
        "chunks": chunks,
        "current": 0,
        "attempts": 0,
        "mastery": {},
        "done": False,
        "question": first.question[:600],
        "messages": [
            {
                "role": "kili",
                "text": first.message.strip(),
                "question": first.question.strip()[:600],
                "chunk": 0,
            }
        ],
    }
    try:
        with transaction.atomic():
            s, _ = TutorSession.objects.update_or_create(user=request.user, subsection=sub, defaults=fields)
    except IntegrityError:  # double-click race: the other request created it
        s = TutorSession.objects.get(user=request.user, subsection=sub)
    return Response(_state(s), status=status.HTTP_201_CREATED)


class ReplyIn(serializers.Serializer):
    message = serializers.CharField(max_length=1000, trim_whitespace=True)
    lang = serializers.CharField(max_length=12, required=False, allow_blank=True)


@api_view(["POST"])
def tutor_reply(request, pk):
    """The learner answers Kili's check question → feedback, then a re-explanation or the next idea."""
    sub = get_viewable_subsection(request.user, pk)
    if denied := _blocked(request.user):
        return denied
    ser = ReplyIn(data=request.data)
    ser.is_valid(raise_exception=True)
    answer = ser.validated_data["message"]
    s = TutorSession.objects.filter(user=request.user, subsection=sub).first()
    if not s:
        return Response({"code": "no_session"}, status=status.HTTP_404_NOT_FOUND)
    if s.done:
        return Response({"code": "session_done"}, status=status.HTTP_409_CONFLICT)
    if denied := _charge(request.user):
        return denied
    try:
        turn = assess(sub, s, answer, _lang(request, sub), request.user)
    except Exception:
        log.exception("tutor turn failed for lesson %s", sub.id)
        return Response({"code": "tutor_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    score = min(1.0, max(0.0, float(turn.score)))
    with transaction.atomic():
        s = TutorSession.objects.select_for_update().get(pk=s.pk)
        if s.done:
            return Response(_state(s))
        i = s.current
        first_try = s.attempts == 0
        s.attempts += 1
        s.mastery[str(i)] = round(max(score, float(s.mastery.get(str(i), 0.0))), 3)
        msgs = [*s.messages, {"role": "me", "text": answer}]
        if score >= PASS or s.attempts >= MAX_TRIES:
            s.current, s.attempts = i + 1, 0
            s.done = s.current >= len(s.chunks)
            s.question = "" if s.done else turn.next_question.strip()[:600]
            msgs.append(
                {
                    "role": "kili",
                    "text": f"{turn.feedback.strip()}\n\n{turn.next_message.strip()}".strip(),
                    "question": s.question,
                    "chunk": min(s.current, len(s.chunks) - 1),
                    "score": round(score, 2),
                    "moved_on": True,
                }
            )
        else:
            s.question = turn.reexplain_question.strip()[:600]
            msgs.append(
                {
                    "role": "kili",
                    "text": f"{turn.feedback.strip()}\n\n{turn.reexplain.strip()}".strip(),
                    "question": s.question,
                    "chunk": i,
                    "score": round(score, 2),
                    "moved_on": False,
                }
            )
        s.messages = msgs[-MAX_MESSAGES:]
        s.save()
    if first_try:  # adaptive mastery: the first answer to each check question
        from apps.adaptive.services import observe_lesson

        observe_lesson(request.user, sub, score)
    return Response(_state(s))
