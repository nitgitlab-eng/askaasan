"""/ws/live/ — Live Class: hands-free voice + camera/screen snapshots, Kili teaching in real time.

Protocol (client → server): auth{token} · start{mode, topic, lesson_id} · frame{image: data-URL, reason: change|snapshot}
· say{text} · heartbeat · cancel · end.  Server → client: ready · started · start/delta/done (a Kili turn) · silent
· frame_ok · mascot · summary · error.
Snapshots live only in memory for the current turn; they are never written to the database or logs."""

import asyncio
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.http import Http404
from django.utils import timezone

from apps.accounts.preferences import upgrade
from apps.mentor.consumers import SocketAuth
from apps.mentor.websearch import count_search, note_search, search_allowed
from llm.base import ChatMessage, Image, LLMError, LLMRequest
from llm.guard import OutputFilter, screen_turn
from llm.images import decode_data_url
from llm.prompts.guardrails import CRISIS_NOTE, search_note
from llm.prompts.live import GLANCE, SILENT, build_live_system
from llm.prompts.tutor import build_tutor_system
from llm.router import aclose, resolve
from llm.usage import finish

from .models import LiveSession, LiveTurn

log = logging.getLogger(__name__)

FRAME_MAX_BYTES = 600_000  # a 1024px JPEG is ~100–250 KB
MIN_FRAME_GAP = 2.0  # seconds between accepted snapshots
GLANCE_GAP = 20.0  # Kili speaks up on its own at most this often
FRAME_FRESH = 90.0  # a snapshot older than this isn't attached to a reply
HISTORY = 16
CLOCK_EVERY = 15.0  # server bills time itself; client heartbeats are no longer trusted
MAX_SESSION_SECONDS = 60 * 60
MAX_TEXT = 2000

GREETING = "[The live class has just started. Greet the learner warmly in ONE short sentence, then {ask}.]"
GREETING_ASK = {
    "camera": "ask them to hold their notebook or book up to the camera so you can see what they're working on",
    "screen": "ask them to open what they're working on on their screen",
    "none": "ask what they'd like to learn or where they're stuck (this is voice only, so don't ask to see anything)",
}


def _decode(data_url: str) -> Image | None:
    return decode_data_url(data_url, FRAME_MAX_BYTES)


async def _feature_blocked(user, feature: str) -> str | None:
    from channels.db import database_sync_to_async

    from apps.orgs.extras import refusal

    return await database_sync_to_async(refusal)(user, feature)


class LiveConsumer(SocketAuth, AsyncJsonWebsocketConsumer):
    feature = "live"
    session: LiveSession | None = None

    async def connect(self):
        self.task: asyncio.Task | None = None
        self.task_kind = ""
        self.history: list[ChatMessage] = []
        self.frame: tuple[Image, float] | None = None
        self.last_frame_at = 0.0
        self.last_glance = 0.0
        self.last_tick = 0.0
        self.frames_blocked = False
        self.system = ""
        self.mode = "camera"
        await self.accept()

    async def disconnect(self, code):
        if self.task and not self.task.done():
            self.task.cancel()
        if getattr(self, "clock", None):
            self.clock.cancel()
        if self.session and not self.session.ended_at:
            await self._tick()
            await database_sync_to_async(self._close_session)()

    # ── dispatch ─────────────────────────────────────────────────────
    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "auth":
            if self.user:
                await self.reauth(content.get("token") or "")
                return
            if not await self.authenticate(content.get("token") or ""):
                await self.send_json({"type": "error", "code": "unauthorized"})
                await self.close(code=4401)
                return
            if code := await _feature_blocked(
                self.user, "live"
            ):  # school switched it off, or no guardian yet
                await self.send_json({"type": "error", "code": code})
                await self.close(code=4403)
                return
            await self.send_json({"type": "ready"})
            return
        if not self.user:
            await self.send_json({"type": "error", "code": "unauthorized"})
            return
        if await self.expired():
            return
        if kind in ("start", "frame", "say") and not await self.still_allowed():
            return  # each of these can lead to a paid AI turn
        if kind == "start" and not self.session:
            await self._start(content)
        elif not self.session:
            await self.send_json({"type": "error", "code": "not_started"})
        elif kind == "frame":
            await self._frame(content)
        elif kind == "say":
            await self._say(content)
        elif kind == "heartbeat":
            await self._tick()
        elif kind == "cancel" and self.task and not self.task.done():
            self.task.cancel()
        elif kind == "end":
            await self._end()

    # ── start ────────────────────────────────────────────────────────
    async def _start(self, content):
        from apps.billing.services import PlanLimit, check

        try:
            await database_sync_to_async(check)(self.user, "live_minutes_per_day", 0.5)
        except PlanLimit as e:
            await self.send_json({"type": "error", "retryable": False, **e.payload()})
            return
        try:
            provider, _ = await database_sync_to_async(resolve)("vision")
            await aclose(provider)
        except LLMError as e:
            await self.send_json({"type": "error", "code": e.code, "retryable": False})
            return
        self.mode = content.get("mode") if content.get("mode") in ("camera", "screen", "none") else "camera"
        topic = str(content.get("topic") or "")[:300]
        self.session, lesson = await database_sync_to_async(self._create)(topic, content.get("lesson_id"))
        self.system = await database_sync_to_async(self._system)(topic, lesson)
        self.last_tick = time.monotonic()
        self.clock = asyncio.create_task(self._clock())
        left = await database_sync_to_async(self._minutes_left)()
        await self.send_json(
            {"type": "started", "session_id": self.session.id, "minutes_left": left, "lesson": lesson}
        )
        self._spawn(
            "reply",
            self._turn(
                GREETING.format(ask=GREETING_ASK[self.mode]),
                with_frame=False,
                proactive=True,
                save_user=False,
            ),
        )

    def _create(self, topic, lesson_id):
        lesson = None
        sub = None
        if lesson_id:
            from apps.learning.access import get_viewable_subsection

            try:
                sub = get_viewable_subsection(self.user, int(lesson_id))
                lesson = {
                    "id": sub.id,
                    "title": sub.title,
                    "objective": sub.objective,
                    "course": sub.section.curriculum.title,
                }
            except (Http404, ValueError, TypeError):  # not visible / bad id → plain topic class
                sub = None
        s = LiveSession.objects.create(
            user=self.user, mode=self.mode, topic=topic or (lesson["title"] if lesson else ""), lesson=sub
        )
        return s, lesson

    def _system(self, topic, lesson):
        prefs = upgrade(self.user.preferences.data)
        return build_live_system(
            build_tutor_system(self.user.profile, prefs, prefs["mascot"]["name"]), self.mode, topic, lesson
        )

    def _minutes_left(self):
        from apps.billing.services import limit_of, usage

        m = limit_of(self.user, "live_minutes_per_day")
        return None if m is None else max(0, round(m - usage(self.user, "live_minutes_per_day"), 1))

    # ── frames ───────────────────────────────────────────────────────
    async def _frame(self, content):
        if self.mode == "none" or self.frames_blocked:
            return
        now = time.monotonic()
        if now - self.last_frame_at < MIN_FRAME_GAP:
            await self.send_json({"type": "frame_ok", "accepted": False, "reason": "too_fast"})
            return
        img = _decode(content.get("image"))
        if not img:
            await self.send_json({"type": "error", "code": "bad_frame"})
            return
        if not await database_sync_to_async(self._charge_frame)():
            self.frames_blocked = True
            await self.send_json({"type": "error", "code": "vision_budget_exceeded", "retryable": False})
            return
        self.frame, self.last_frame_at = (img, now), now
        await self.send_json({"type": "frame_ok", "accepted": True})
        busy = self.task and not self.task.done()
        if (
            content.get("reason") == "change"
            and not busy
            and self.history
            and now - self.last_glance > GLANCE_GAP
            and not await self._tick()
        ):
            self.last_glance = now
            what = "page" if self.mode == "camera" else "screen"
            self._spawn(
                "glance",
                self._turn(
                    GLANCE.format(what=what), with_frame=True, proactive=True, save_user=False, glance=True
                ),
            )

    def _charge_frame(self) -> bool:
        from apps.providers.services import BudgetExceeded, charge
        from apps.providers.services import resolve as resolve_cfg

        try:
            charge(
                self.user, "vision_frames", 1, resolve_cfg("vision").limits.get("vision_frames_per_day", 0)
            )
        except BudgetExceeded:
            return False
        LiveSession.objects.filter(pk=self.session.pk).update(frames=self.session.frames + 1)
        self.session.frames += 1
        return True

    # ── learner speaks / types ───────────────────────────────────────
    async def _say(self, content):
        text = str(content.get("text") or "").strip()[:MAX_TEXT]
        if not text or await self._tick():
            return
        screened = await database_sync_to_async(screen_turn)(text, self.user.pk, "live")
        text = screened.text  # secrets masked before the model, a search or the transcript
        if self.task and not self.task.done():
            if self.task_kind == "glance":
                self.task.cancel()  # the learner talking always wins over an unprompted remark
                await asyncio.sleep(0)
            else:
                await self.send_json({"type": "error", "code": "busy"})
                return
        self._spawn(
            "reply",
            self._turn(text, with_frame=True, proactive=False, save_user=True, crisis=screened.crisis),
        )

    def _spawn(self, kind, coro):
        self.task_kind = kind
        self.task = self.spawn(coro)

    async def _turn(self, text, *, with_frame, proactive, save_user, glance=False, crisis=False):
        image = None
        if with_frame and self.frame and time.monotonic() - self.frame[1] < FRAME_FRESH:
            image = self.frame[0]
        if glance and not image:
            return
        try:
            provider, model = await database_sync_to_async(resolve)("vision")
        except LLMError as e:
            await self.send_json({"type": "error", "code": e.code, "retryable": False})
            return
        msgs = [*self.history[-HISTORY:], ChatMessage("user", text, images=[image] if image else [])]
        # A question the learner asks may look up current facts; an unprompted glance never searches.
        web = not glance and await database_sync_to_async(search_allowed)(self.user)
        system = self.system + search_note(web) + (CRISIS_NOTE if crisis else "")
        req = LLMRequest(
            model=model, system=system, messages=msgs, max_tokens=1200, effort="low", web_search=web
        )
        parts, final, started, searched = [], None, False, False
        out = OutputFilter()  # no images, and no links the model wrote itself
        if not glance:
            await self.send_json({"type": "mascot", "state": "thinking"})
        try:
            async for ev in provider.stream(req):
                if ev.done:
                    final = ev
                    break
                if ev.status == "searching":
                    if not searched:
                        searched = True
                        await database_sync_to_async(count_search)(self.user)
                        await self.send_json({"type": "status", "state": "searching"})
                    continue
                piece = out.feed(ev.delta)
                if not piece:
                    continue
                parts.append(piece)
                if glance and not started:
                    so_far = "".join(parts).lstrip()
                    if SILENT.startswith(so_far[: len(SILENT)]) and len(so_far) < len(SILENT) + 2:
                        continue  # still might be the silent marker — hold back
                if not started:
                    started = True
                    await self.send_json({"type": "start", "proactive": proactive, "saw": bool(image)})
                    await self.send_json({"type": "mascot", "state": "talking"})
                    await self.send_json({"type": "delta", "text": "".join(parts)})
                else:
                    await self.send_json({"type": "delta", "text": piece})
            if tail := out.flush():
                parts.append(tail)
                if started:
                    await self.send_json({"type": "delta", "text": tail})
        except asyncio.CancelledError:
            await finish(provider, self.user)
            if started:
                await self._remember(text, "".join(parts), image, proactive, save_user)
                await self.send_json({"type": "done", "stop_reason": "cancelled"})
            await self.send_json({"type": "mascot", "state": "idle"})
            raise
        except LLMError as e:
            await finish(provider, self.user)
            log.warning("live turn failed: %s", e.code)
            await self.send_json({"type": "error", "code": e.code, "retryable": e.retryable})
            await self.send_json({"type": "mascot", "state": "confused"})
            return
        await finish(provider, self.user)
        if web:  # providers that report sources but no "searching" event still count
            await database_sync_to_async(note_search)(self.user, searched, final)
        reply = "".join(parts).strip()
        if glance and (not reply or reply.startswith(SILENT)):
            await self.send_json({"type": "silent"})
            return
        if not started:  # whole reply arrived in the final chunk
            await self.send_json({"type": "start", "proactive": proactive, "saw": bool(image)})
            await self.send_json({"type": "delta", "text": reply})
        if final and final.stop_reason == "refusal":
            reply = reply or "Let's keep our class on your studies. What are you working on?"
        turn_id = await self._remember(text, reply, image, proactive, save_user)
        await self.send_json(
            {
                "type": "done",
                "stop_reason": final.stop_reason if final else None,
                "turn_id": turn_id,
                "sources": (final.sources if final and web else None) or [],
            }
        )
        await self.send_json({"type": "mascot", "state": "idle"})

    async def _remember(self, text, reply, image, proactive, save_user):
        # History keeps text only; a marker tells the model a snapshot was seen at that point.
        self.history += [
            ChatMessage("user", text + (" [snapshot attached]" if image else "")),
            ChatMessage("assistant", reply),
        ]
        return await database_sync_to_async(self._save_turns)(
            text if save_user else None, reply, bool(image), proactive
        )

    def _save_turns(self, user_text, reply, saw, proactive):
        if user_text:
            LiveTurn.objects.create(session=self.session, role="user", text=user_text, saw_frame=saw)
        if reply:
            return LiveTurn.objects.create(
                session=self.session, role="assistant", text=reply, saw_frame=saw, proactive=proactive
            ).id
        return None

    # ── time, limits, end ────────────────────────────────────────────
    async def _clock(self):
        try:
            while self.session and not self.session.ended_at:
                await asyncio.sleep(CLOCK_EVERY)
                if not await self.still_allowed():  # a quiet class still notices a revoked account or feature
                    return
                await self._tick()
        except asyncio.CancelledError:
            pass

    async def _tick(self) -> bool:
        """Bill the real time since the last tick. Returns True if the class had to end (limit reached)."""
        if not self.session or self.session.ended_at:
            return True
        now = time.monotonic()
        secs = max(0.0, now - self.last_tick)
        self.last_tick = now
        over = await database_sync_to_async(self._add_seconds)(secs)
        if not over and self.session.seconds >= MAX_SESSION_SECONDS:
            over = {"code": "session_too_long"}
        if over:
            await self.send_json({"type": "error", "retryable": False, **over})
            await self._end()
            return True
        return False

    def _add_seconds(self, secs):
        from django.db import transaction

        from apps.billing.services import PlanLimit, check, lock_user
        from apps.providers.services import charge

        with (
            transaction.atomic()
        ):  # record + check under the user's lock, so parallel classes see each other's time
            lock_user(self.user)
            charge(self.user, "live_seconds", secs, 0)
            LiveSession.objects.filter(pk=self.session.pk).update(seconds=self.session.seconds + int(secs))
            self.session.seconds += int(secs)
            try:
                check(self.user, "live_minutes_per_day", 0)
            except PlanLimit as e:
                return e.payload()
        return None

    def _close_session(self):
        self.session.ended_at = timezone.now()
        self.session.save(update_fields=["ended_at"])

    async def _end(self):
        if self.task and not self.task.done():
            self.task.cancel()
        if self.session.ended_at:
            return
        await database_sync_to_async(self._close_session)()
        await self.send_json({"type": "mascot", "state": "thinking"})
        from .services import summarise

        summary = await database_sync_to_async(summarise)(self.session)
        await self.send_json({"type": "summary", "session_id": self.session.id, "summary": summary})
        await self.send_json({"type": "mascot", "state": "celebrate" if summary else "idle"})
