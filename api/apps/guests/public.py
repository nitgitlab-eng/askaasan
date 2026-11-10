"""Public guest pages (/g/:slug). No login, no cookies: every view runs without authentication, is throttled per IP,
only ever touches the link's own target, and never returns answer keys before an answer or other people's data."""

import asyncio

from django.core import signing
from django.core.cache import cache
from django.db.models import F
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle

from apps.learning import activities as acts
from llm.base import ChatMessage, LLMError, LLMRequest
from llm.prompts.roleplay import character_system

from .models import GuestLink, GuestOptOut, GuestRolePlay, GuestVisitor
from .services import (
    AI_GRADED,
    UNSUB_SALT,
    USABLE,
    charge_ai,
    client_ip,
    course_lessons,
    guest_activity,
    guest_lesson,
    ip_hash,
    lesson_really_done,
    limit,
    new_visitor,
    send_magic_link,
    use_magic,
    visitor_from,
)


class _IpThrottle(SimpleRateThrottle):
    """Keyed by client IP always (guest views carry no auth); IPv6 clients are bucketed by /64."""

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": client_ip(request)}


class ReadThrottle(_IpThrottle):
    scope, rate = "guest_read", "300/hour"


class StartThrottle(_IpThrottle):
    scope, rate = "guest_start", "20/hour"


class AttemptThrottle(_IpThrottle):
    scope, rate = "guest_attempt", "200/hour"


class ChatThrottle(_IpThrottle):
    scope, rate = "guest_chat", "60/hour"


class MailThrottle(_IpThrottle):
    scope, rate = "guest_mail", "5/hour"


def public(*throttles):
    def deco(fn):
        fn = throttle_classes(list(throttles))(fn)
        fn = permission_classes([permissions.AllowAny])(fn)
        return authentication_classes([])(fn)

    return deco


def _link(slug) -> GuestLink:
    return get_object_or_404(
        GuestLink.objects.select_related("course__owner__profile", "scenario", "org"), slug=slug[:48]
    )


def _refuse(st: str) -> Response:
    return Response(
        {"code": f"link_{st}"},
        status=status.HTTP_410_GONE if st in ("expired", "inactive", "full") else status.HTTP_404_NOT_FOUND,
    )


def _visitor_or_401(request, link) -> GuestVisitor | Response:
    v = visitor_from(request, link)
    if not v:
        return Response({"code": "guest_token_required"}, status=status.HTTP_401_UNAUTHORIZED)
    return v


def _brand(link) -> dict | None:
    o = link.org
    return {"name": o.display_name or o.name, "color": o.brand_color, "logo_url": o.logo_url} if o else None


def _target(link) -> dict | None:
    if link.target_kind == "course" and link.course_id and link.course.published_at:
        c = link.course
        lessons = [{"id": s.id, "title": s.title} for s in course_lessons(c)[:60]]
        return {
            "kind": "course",
            "title": c.title or c.goal,
            "description": c.description,
            "cover_emoji": c.cover_emoji,
            "level": c.level,
            "language": c.language,
            "lessons": lessons,
        }
    if link.target_kind == "roleplay" and link.scenario_id:
        s = link.scenario
        return {
            "kind": "roleplay",
            "title": s.title,
            "description": s.summary,
            "cover_emoji": s.emoji,
            "learner_role": s.learner_role,
            "character": s.character.get("name", ""),
            "objectives": s.objectives,
        }
    return None


def _me(v: GuestVisitor | None) -> dict | None:
    if not v:
        return None
    return {
        "name": v.name,
        "has_email": bool(v.email),
        "lessons_done": v.lessons_done or [],
        "completed": bool(v.completed_at),
        "claimed": bool(v.claimed_by_id),
    }


@api_view(["GET"])
@public(ReadThrottle)
def landing(request, slug):
    link = _link(slug)
    st = link.state()
    if st == "no_target":
        return _refuse(st)
    if st in ("inactive", "expired"):  # nothing about the content once a link is off
        return Response(
            {
                "slug": link.slug,
                "state": st,
                "label": "",
                "collect_email": False,
                "brand": None,
                "target": None,
                "me": None,
            }
        )
    key = f"guest-open:{link.id}:{ip_hash(request)[:24]}"
    if cache.add(key, 1, 3600):  # one open per IP per hour
        GuestLink.objects.filter(pk=link.pk).update(opens=F("opens") + 1)
    return Response(
        {
            "slug": link.slug,
            "label": link.label,
            "state": st,
            "collect_email": link.collect_email,
            "brand": _brand(link),
            "target": _target(link),
            "me": _me(visitor_from(request, link)),
        }
    )


class StartIn(serializers.Serializer):
    name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)


@api_view(["POST"])
@public(StartThrottle)
def start(request, slug):
    link = _link(slug)
    if v := visitor_from(request, link):
        return Response({"me": _me(v)})
    ser = StartIn(data=request.data)
    ser.is_valid(raise_exception=True)
    name, email = (
        ser.validated_data.get("name", "").strip(),
        ser.validated_data.get("email", "").strip().lower(),
    )
    if link.collect_email:
        if not name or not email:
            return Response({"code": "name_email_required"}, status=status.HTTP_400_BAD_REQUEST)
        existing = GuestVisitor.objects.filter(link=link, email=email).order_by("created_at").first()
        if existing:
            # Never hand someone's progress to whoever types their address: the owner gets a (capped, fixed-text) email
            # to resume, and this person starts fresh — the response is identical either way (no enumeration).
            send_magic_link(existing)
    else:
        email = ""
    v, raw = new_visitor(link, request, name, email)
    if not v:
        return _refuse(raw)
    return Response({"token": raw, "me": _me(v)}, status=status.HTTP_201_CREATED)


@api_view(["POST"])
@public(StartThrottle)
def resume(request, slug):
    link = _link(slug)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v, raw = use_magic(link, str(request.data.get("magic") or "")[:400])
    if not v:
        return Response({"code": "bad_magic_link"}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"token": raw, "me": _me(v)})


@api_view(["POST"])
@public(MailThrottle)
def email_link(request, slug):
    """'Email me a link to continue on another device' — only to the address the guest gave when starting."""
    link = _link(slug)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    if not v.email:
        return Response({"code": "no_email"}, status=status.HTTP_400_BAD_REQUEST)
    if err := send_magic_link(v):
        code = {"mail_limit": status.HTTP_429_TOO_MANY_REQUESTS}.get(err, status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response({"code": err}, status=code)
    return Response({"ok": True})


@api_view(["GET"])
@public(ReadThrottle)
def lesson(request, slug, lesson_id):
    link = _link(slug)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    sub = guest_lesson(link, lesson_id)
    if not sub:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    mine = {}
    for a in v.attempts.filter(activity__subsection=sub):
        mine[a.activity_id] = {
            "score": a.score,
            "correct": a.correct,
            "feedback": a.feedback,
            "answer": a.answer,
        }
    ids = [s.id for s in course_lessons(link.course)]
    i = ids.index(sub.id)
    return Response(
        {
            "id": sub.id,
            "title": sub.title,
            "objective": sub.objective,
            "explanation_md": sub.explanation_md,
            "key_points": sub.key_points,
            "next_id": ids[i + 1] if i + 1 < len(ids) else None,
            "position": i + 1,
            "total": len(ids),
            "activities": [
                {
                    "id": a.id,
                    "type": a.type,
                    "title": a.title,
                    "payload": a.payload,
                    "attempt": mine.get(a.id),
                    "locked": a.type in AI_GRADED,
                }
                for a in sub.activities.filter(kind="lesson")
            ],
        }
    )


@api_view(["POST"])
@public(AttemptThrottle)
def attempt(request, slug, activity_id):
    link = _link(slug)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    a = guest_activity(link, activity_id)
    if not a:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if a.type in AI_GRADED:
        return Response({"code": "signup_required"}, status=status.HTTP_403_FORBIDDEN)
    answer = request.data.get("answer")
    if not isinstance(answer, dict) or len(str(answer)) > 20000:
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    if v.attempts.count() >= 500:
        return Response({"code": "too_many_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        g = acts.grade(a, answer, link.course.language)
    except Exception:  # noqa: BLE001 — malformed answers grade as wrong rather than 500
        return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
    v.attempts.create(activity=a, answer=answer, score=g.score, correct=g.correct, feedback=g.feedback[:2000])
    return Response(
        {"score": round(g.score, 3), "correct": g.correct, "feedback": g.feedback, "reveal": g.reveal}
    )


@api_view(["POST"])
@public(AttemptThrottle)
def lesson_done(request, slug, lesson_id):
    link = _link(slug)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    sub = guest_lesson(link, lesson_id)
    if not sub:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if not lesson_really_done(v, sub):
        return Response({"code": "answer_all_first"}, status=status.HTTP_409_CONFLICT)
    done = list(v.lessons_done or [])
    if sub.id not in done:
        done.append(sub.id)
        v.lessons_done = done[-200:]
        v.save(update_fields=["lessons_done", "last_seen"])
    return Response({"me": _me(v)})


@api_view(["POST"])
@public(AttemptThrottle)
def finish(request, slug):
    link = _link(slug)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    did_something = bool(v.lessons_done) or v.roleplays.filter(status="completed").exists()
    if not v.completed_at and did_something:  # "finished" only counts real work, not a click on Finish
        v.completed_at = timezone.now()
        v.save(update_fields=["completed_at", "last_seen"])
    return Response({"me": _me(v)})


@api_view(["GET"])
@public(ReadThrottle)
def summary(request, slug):
    link = _link(slug)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    atts = list(v.attempts.all())
    rp = v.roleplays.filter(status="completed").order_by("-created_at").first()
    return Response(
        {
            "me": _me(v),
            "target": _target(link),
            "brand": _brand(link),
            "answers": len(atts),
            "correct": sum(1 for a in atts if a.correct),
            "avg_score": round(sum(a.score for a in atts) / len(atts), 3) if atts else None,
            "roleplay": {"overall": rp.result.get("overall"), "summary": rp.result.get("summary")}
            if rp and rp.result
            else None,
        }
    )


# ── Guest role-play (reuses the role-play engine's character prompt + evaluator) ──


def _turn_cap(sc) -> int:
    return min(sc.max_turns, limit("GUEST_ROLEPLAY_TURNS", 6))


def _rp_out(gr: GuestRolePlay) -> dict:
    learner = sum(1 for t in gr.turns if t["role"] == "learner")
    sc = gr.scenario
    return {
        "id": gr.id,
        "status": gr.status,
        "result": gr.result,
        "turns": gr.turns,
        "turns_left": max(0, _turn_cap(sc) - learner),
        "scenario": {
            "title": sc.title,
            "emoji": sc.emoji,
            "summary": sc.summary,
            "learner_role": sc.learner_role,
            "setting": sc.setting,
            "character": {"name": sc.character.get("name", ""), "persona": sc.character.get("persona", "")},
            "objectives": sc.objectives,
        },
    }


def _guest_rp(request, slug) -> tuple[GuestLink, GuestVisitor, GuestRolePlay | None] | Response:
    link = _link(slug)
    if link.target_kind != "roleplay" or not link.scenario_id:
        return Response({"code": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if (st := link.state()) not in USABLE:
        return _refuse(st)
    v = _visitor_or_401(request, link)
    if isinstance(v, Response):
        return v
    return link, v, v.roleplays.filter(scenario=link.scenario).order_by("-created_at").first()


@api_view(["GET", "POST"])
@public(ReadThrottle)
def roleplay(request, slug):
    """GET → current session (or null) · POST → start (or resume the active) session."""
    got = _guest_rp(request, slug)
    if isinstance(got, Response):
        return got
    link, v, gr = got
    if request.method == "POST" and (
        not gr or (gr.status == "completed" and request.data.get("again") is True)
    ):
        if v.roleplays.count() >= 3:
            return Response({"code": "too_many_sessions"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        gr = GuestRolePlay.objects.create(
            visitor=v,
            scenario=link.scenario,
            turns=[{"role": "character", "text": link.scenario.opening_line}],
        )
    return Response(_rp_out(gr) if gr else None)


def _complete_text(system: str, history: list[ChatMessage]) -> str:
    from llm.router import aclose, resolve
    from llm.usage import flush_usage

    provider, model = resolve("tutor")

    async def run():
        try:
            return await provider.complete(
                LLMRequest(model=model, system=system, messages=history, max_tokens=400, effort="low")
            )
        finally:
            await aclose(provider)

    try:
        from llm.dbconn import release_db

        release_db()
        return asyncio.run(run())
    finally:
        flush_usage(provider)


class SayIn(serializers.Serializer):
    text = serializers.CharField(max_length=1000, trim_whitespace=True)


@api_view(["POST"])
@public(ChatThrottle)
def roleplay_say(request, slug):
    got = _guest_rp(request, slug)
    if isinstance(got, Response):
        return got
    link, _v, gr = got
    if not gr or gr.status != "active":
        return Response({"code": "no_session"}, status=status.HTTP_409_CONFLICT)
    ser = SayIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if sum(1 for t in gr.turns if t["role"] == "learner") >= _turn_cap(gr.scenario):
        return Response({"code": "turn_limit"}, status=status.HTTP_409_CONFLICT)
    if not charge_ai(link, request):
        return Response({"code": "guest_ai_limit"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    from llm.guard import clean_output, screen_turn
    from llm.prompts.guardrails import CRISIS_NOTE

    screened = screen_turn(ser.validated_data["text"], None, "guest_roleplay")  # secrets never stored or sent
    turns = [*gr.turns, {"role": "learner", "text": screened.text}]
    history = [ChatMessage("user" if t["role"] == "learner" else "assistant", t["text"]) for t in turns]
    if history[0].role == "assistant":
        history.insert(0, ChatMessage("user", "(The conversation begins.)"))
    try:
        reply = _complete_text(
            character_system(gr.scenario, link.course.language if link.course_id else "en")
            + (CRISIS_NOTE if screened.crisis else ""),
            history,
        ).strip()
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    reply = clean_output(reply)
    gr.turns = [*turns, {"role": "character", "text": reply[:2000]}]
    gr.save(update_fields=["turns"])
    return Response(_rp_out(gr))


@api_view(["POST"])
@public(ChatThrottle)
def roleplay_end(request, slug):
    from apps.roleplay.services import MIN_TURNS_FOR_EVAL

    got = _guest_rp(request, slug)
    if isinstance(got, Response):
        return got
    link, _v, gr = got
    if not gr:
        return Response({"code": "no_session"}, status=status.HTTP_409_CONFLICT)
    if gr.status == "completed":
        return Response(_rp_out(gr))
    if sum(1 for t in gr.turns if t["role"] == "learner") < MIN_TURNS_FOR_EVAL:
        return Response(
            {"code": "too_short", "min_turns": MIN_TURNS_FOR_EVAL}, status=status.HTTP_400_BAD_REQUEST
        )
    if not charge_ai(link, request, units=2):
        return Response({"code": "guest_ai_limit"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        result = _evaluate(gr)
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    gr.result, gr.status = result, "completed"
    gr.save(update_fields=["result", "status"])
    return Response(_rp_out(gr))


def _evaluate(gr: GuestRolePlay) -> dict:
    """The role-play engine's evaluator, run on an in-memory session (guests have no RolePlaySession row)."""
    from types import SimpleNamespace

    from apps.roleplay import services as rp

    turns = [SimpleNamespace(role=t["role"], text=t["text"]) for t in gr.turns]

    class _Turns(list):
        def all(self):
            return self

    fake = SimpleNamespace(scenario=gr.scenario, turns=_Turns(turns), language="en")
    return rp.evaluate(fake)


# ── Campaign email opt-out ───────────────────────────────────────────

UNSUB_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Unsubscribe · Aasan</title></head><body style="font-family:system-ui,sans-serif;max-width:32rem;margin:3rem auto;padding:0 1rem">
<h1 style="font-size:1.4rem">Stop demo-lesson emails?</h1>
<p>We won't send demo-lesson emails to this address again. · இந்த முகவரிக்கு இனி டெமோ பாட மின்னஞ்சல்கள் அனுப்ப மாட்டோம்.</p>
<form method="post"><input type="hidden" name="t" value="{token}">
<button type="submit" style="padding:.6rem 1.2rem;font-size:1rem">Unsubscribe · விலகு</button></form></body></html>"""


@api_view(["GET", "POST"])
@public(ReadThrottle)
def unsubscribe(request):
    """GET shows a confirm page (mail scanners prefetch links); only the POST from that page opts the address out."""
    from django.utils.html import escape

    raw = str((request.data.get("t") if request.method == "POST" else request.query_params.get("t")) or "")[
        :500
    ]
    try:
        data = signing.loads(raw, salt=UNSUB_SALT, max_age=3 * 365 * 24 * 3600)
    except signing.BadSignature:
        return HttpResponse(
            "This unsubscribe link is not valid.", status=400, content_type="text/plain; charset=utf-8"
        )
    if request.method == "GET":
        resp = HttpResponse(UNSUB_PAGE.format(token=escape(raw)), content_type="text/html; charset=utf-8")
        resp["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"
        return resp
    GuestOptOut.objects.get_or_create(email=str(data.get("e", "")).lower()[:254])
    return HttpResponse(
        "You're unsubscribed. You won't get demo-lesson emails at this address again.\n"
        "நீங்கள் விலகிவிட்டீர்கள். இனி இந்த முகவரிக்கு மின்னஞ்சல்கள் வராது.",
        content_type="text/plain; charset=utf-8",
    )
