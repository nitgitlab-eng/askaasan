"""/ws/workshop/<session_id>/ — one learner's AI-led workshop session.

Client → server: auth{token} · say{text} · next · control{action} · step_done{step} · attention{kind} · raise_hand
· cancel. Server → client: ready{session, turns, nudges[], suggest[]} · start/delta/done{stop_reason} (one host
turn) · progress{session} · suggest{chips} · pace{status, minutes_left, message} · paused{reason} · error{code}
· staff_nudge{id, text, from, at} (org runs).

A `say`, `next` or `control` that arrives while the host is still speaking interrupts it: the partial reply is saved
as cancelled (done{stop_reason: "cancelled"}) and the new input is handled straight away. There is no "busy".

On org (institution) runs every state change and clock tick also publishes the learner's throttled monitor tile
(monitor.py), and staff nudges arrive through the session's own channel group.

The server owns all state (services.py), so a disconnect never ends the session: reconnecting sends `ready` with the
full state and the last few turns. The learner is never moved on or submitted for: only their own actions change it."""

import asyncio
import json
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder

from apps.mentor.consumers import SocketAuth, _token_exp
from apps.mentor.websearch import count_search, note_search, search_allowed
from llm.base import ChatMessage, LLMError, LLMRequest
from llm.guard import OutputFilter, screen_turn
from llm.prompts.guardrails import CRISIS_NOTE, search_note
from llm.router import resolve
from llm.usage import finish

from . import monitor, services
from .models import WorkshopRun, WorkshopSession

log = logging.getLogger(__name__)

CLOCK_EVERY = 15.0
MAX_TEXT = 2000
MAX_FRAME = 16 * 1024  # bytes of one client message (a `say` is ≤ MAX_TEXT characters)
RATE_PER_S, RATE_BURST = 10.0, 20  # per-socket token bucket: extra messages are dropped
CONTROLS = (
    "slower",
    "again",
    "example",
    "tamil",
    "english",
    "yes_next",
    "not_yet",
    "not_sure",
    "stuck",
    "continue",
)
QUIET_AFTER = (
    60.0  # seconds without learner input (and the host not speaking) before the one check-in per item
)
AI_KINDS = ("say", "next", "control", "step_done", "raise_hand")


def _owned(session_id, user_id) -> bool | None:
    """→ None when not the owner's (or, on an org run, the learner is no longer in its classes), else whether the
    session is on an org run."""
    s = WorkshopSession.objects.select_related("run", "user").filter(pk=session_id, user_id=user_id).first()
    if not s:
        return None
    if s.run.audience != WorkshopRun.Audience.ORG:
        return False
    from .org import in_audience

    return True if in_audience(s.run, s.user) else None


def _ready(session_id) -> dict:
    s = services.load(session_id)
    return {
        "session": services.session_out(s),
        "turns": services.recent_turns(s),
        # Staff nudges sent while this learner was offline (≤ 2 h old).
        "nudges": monitor.pending_nudges(s.id),
        "suggest": services.suggest(s.id),
    }


def stop_reason(raw: str | None) -> str:
    """The provider's stop reason in the client's vocabulary: end_turn | max_tokens (cancelled is set by us)."""
    r = (raw or "").lower()
    return "max_tokens" if r in ("max_tokens", "length", "max_output_tokens") else "end_turn"


def _session(session_id) -> dict:
    return services.session_out(services.load(session_id))


def _can_move(sid) -> bool:
    s = services.load(sid)
    return services.ready_to_move(s) or bool(services.ai_paused(s))  # same rule as on_next(consent=True)


class WorkshopConsumer(SocketAuth, AsyncJsonWebsocketConsumer):
    feature = "workshops"

    @classmethod
    async def encode_json(cls, content):
        return json.dumps(content, cls=DjangoJSONEncoder)  # the session object carries datetimes

    async def connect(self):
        self.sid = self.scope["url_route"]["kwargs"]["session_id"]
        self.task: asyncio.Task | None = None
        self.clock: asyncio.Task | None = None
        self.org_run = False
        self._quiet_since = time.monotonic()
        self._tokens, self._refill, self._warned = float(RATE_BURST), time.monotonic(), False
        await self.accept()

    def _rate_ok(self) -> bool:
        at = time.monotonic()
        self._tokens = min(RATE_BURST, self._tokens + (at - self._refill) * RATE_PER_S)
        self._refill = at
        if self._tokens < 1:
            return False
        self._tokens -= 1
        self._warned = False
        return True

    async def receive(self, text_data=None, bytes_data=None, **kwargs):
        """Size, shape and rate checks before any message is parsed or dispatched."""
        if not self._rate_ok():
            if not self._warned:  # one error per burst, then quiet drops
                self._warned = True
                await self.send_json({"type": "error", "code": "rate_limited"})
            return
        if bytes_data is not None or len(text_data or "") > MAX_FRAME:
            await self.send_json({"type": "error", "code": "too_large"})
            return
        try:
            content = await self.decode_json(text_data)
        except (ValueError, RecursionError):
            content = None
        if not isinstance(content, dict):
            await self.send_json({"type": "error", "code": "bad_message"})
            return
        await self.receive_json(content, **kwargs)

    async def still_allowed(self) -> bool:
        """The shared checks, plus: the session is still this learner's (on an org run, still in its classes)."""
        if not await super().still_allowed():
            return False
        if await database_sync_to_async(_owned)(self.sid, self.user.pk) is None:
            await self.send_json({"type": "error", "code": "not_found"})
            await self.close(code=4404)
            return False
        return True

    async def disconnect(self, code):
        if self.task and not self.task.done():
            self.task.cancel()
        if self.clock:
            self.clock.cancel()
        if self.org_run:
            await self.channel_layer.group_discard(monitor.session_group(self.sid), self.channel_name)

    async def staff_nudge(self, event):
        """A message from the learner's teacher (monitor consumer → this session's group). Plain text. Marked delivered,
        so it isn't replayed in the next `ready`."""
        await self.send_json(
            {
                "type": "staff_nudge",
                "id": event.get("id"),
                "text": event["text"],
                "from": event["from"],
                "at": event.get("at"),
            }
        )
        if event.get("id"):
            await database_sync_to_async(monitor.mark_nudge_delivered)(event["id"], self.sid)

    async def _tile(self, urgent: bool = False):
        if self.org_run:
            await monitor.apublish(self.sid, urgent=urgent)

    async def reauth(self, token: str):
        """Same account renewing its token gets the full state again; any other account is refused."""
        from apps.mentor.auth import user_from_token

        user = await user_from_token(token or "")
        if user and user.pk == self.user.pk:
            self.exp = _token_exp(token)
            if not await self.still_allowed():
                return
            await self.send_json({"type": "ready", **await database_sync_to_async(_ready)(self.sid)})
            # The socket may have opened on the prerequisites screen: after Start, a re-auth begins the teaching.
            # opening() only speaks when the current item hasn't been explained yet, so periodic renewals stay silent.
            if not self._busy():
                out = await database_sync_to_async(services.opening)(self.sid)
                if out.note:
                    self._spawn(out.note, out.after, learner=False)
        else:
            await self.send_json({"type": "error", "code": "already_authenticated"})

    # ── dispatch ─────────────────────────────────────────────────────
    async def receive_json(self, content, **kwargs):
        kind = content.get("type")
        if kind == "auth":
            if self.user:
                await self.reauth(content.get("token") or "")
                return
            await self._auth(content.get("token") or "")
            return
        if not self.user:
            await self.send_json({"type": "error", "code": "unauthorized"})
            return
        if await self.expired():
            return
        if kind == "cancel":
            if self.task and not self.task.done():
                self.task.cancel()
            return
        if kind == "attention":
            if not await self.still_allowed():
                return
            out = await database_sync_to_async(services.on_attention)(
                self.sid, str(content.get("kind") or "")
            )
            if out.note and not self._busy():
                self._spawn(out.note, None, learner=False)
            await self._tile()
            return
        if kind not in AI_KINDS:
            await self.send_json({"type": "error", "code": "unknown_type"})
            return
        if not await self.still_allowed():
            return
        self._quiet_since = time.monotonic()
        if (
            kind == "control"
            and content.get("action") == "yes_next"
            and not await database_sync_to_async(_can_move)(self.sid)
        ):
            # A stale "Yes, next" (tapped before the host's new reply replaced the chips) must not cut that reply off.
            await self.send_json({"type": "error", "code": "not_ready"})
            await self._suggest()
            return
        if kind in ("say", "next", "control"):  # step ticks and hands go through even mid-reply
            await self._interrupt()
        learner = False
        if kind == "say":
            text = str(content.get("text") or "").strip()
            if not text:
                await self.send_json({"type": "error", "code": "empty"})
                return
            if len(text) > MAX_TEXT:
                await self.send_json({"type": "error", "code": "too_long"})
                return
            screened = await database_sync_to_async(screen_turn)(text, self.user.pk, "workshop")
            self.crisis = screened.crisis  # read by the host turn that answers this message
            out = await database_sync_to_async(services.on_say)(self.sid, screened.text)
            learner = True
        elif kind == "next":
            out = await database_sync_to_async(services.on_next)(self.sid)
        elif kind == "control":
            action = str(content.get("action") or "")
            if action not in CONTROLS:
                await self.send_json({"type": "error", "code": "bad_control"})
                return
            out = await database_sync_to_async(services.on_control)(self.sid, action)
        elif kind == "step_done":
            out = await database_sync_to_async(services.on_step_done)(self.sid, content.get("step"))
        else:
            out = await database_sync_to_async(services.on_raise_hand)(self.sid)
        await self._apply(out, learner=learner)
        await self._tile(urgent=kind == "raise_hand")

    async def _auth(self, token: str):
        if not await self.authenticate(token):
            await self.send_json({"type": "error", "code": "unauthorized"})
            await self.close(code=4401)
            return
        from apps.orgs.extras import refusal

        if code := await database_sync_to_async(refusal)(self.user, self.feature):
            await self.send_json({"type": "error", "code": code})
            await self.close(code=4403)
            return
        owned = await database_sync_to_async(_owned)(self.sid, self.user.pk)
        if owned is None:
            await self.send_json({"type": "error", "code": "not_found"})
            await self.close(code=4404)
            return
        if owned:
            self.org_run = True
            await self.channel_layer.group_add(monitor.session_group(self.sid), self.channel_name)
            await self._tile()
        ready = await database_sync_to_async(_ready)(self.sid)
        await self.send_json({"type": "ready", **ready})
        if ready["session"]["pace"]:
            await self.send_json({"type": "pace", **ready["session"]["pace"]})
        self.clock = asyncio.create_task(self._clock())
        out = await database_sync_to_async(services.opening)(self.sid)
        if out.note:
            self._spawn(out.note, out.after, learner=False)

    async def _suggest(self, stop: str | None = None):
        """Re-send the chips for this moment, so a refused tap never leaves stale ones on screen."""
        if not self._busy():
            await self.send_json(
                {"type": "suggest", "chips": await database_sync_to_async(services.suggest)(self.sid, stop)}
            )

    async def _apply(self, out: services.Out, *, learner: bool):
        if out.error:
            await self.send_json({"type": "error", "code": out.error})
            await self._suggest()
            return
        if out.progress:
            await self.send_json(
                {"type": "progress", "session": await database_sync_to_async(_session)(self.sid)}
            )
        if out.paused:
            await self.send_json({"type": "paused", "reason": out.paused})
            return
        if out.note:
            if self._busy():  # a step tick during a reply: the state changed, the remark can wait
                return
            self._spawn(out.note, out.after, learner=learner)

    def _busy(self) -> bool:
        return bool(self.task and not self.task.done())

    async def _interrupt(self):
        """Stop the streaming host turn cleanly (its partial is saved as cancelled) before new input is handled."""
        if not self._busy():
            return
        task = self.task
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _spawn(self, note: str, after, *, learner: bool):
        self.task = self.spawn(self._turn(note, after, learner))

    # ── one streamed host turn ───────────────────────────────────────
    async def _turn(self, note: str, after, learner: bool):
        reason = await database_sync_to_async(services.spend)(self.sid, services.HOST_MAX_TOKENS)
        if reason:
            await self.send_json({"type": "paused", "reason": reason})
            return
        try:
            provider, model = await database_sync_to_async(resolve)("tutor")
        except LLMError as e:
            await self.send_json({"type": "error", "code": e.code, "retryable": False})
            return
        system, history = await database_sync_to_async(services.host_context)(self.sid, learner)
        # What the learner says may look up current facts; the host's own pacing turns never search. The workshop note
        # forbids looking up (or handing out) the exercise answers; the answer keys never leave the server anyway.
        web = learner and await database_sync_to_async(search_allowed)(self.user)
        system += search_note(web, kind="workshop")
        if learner and getattr(self, "crisis", False):
            system += CRISIS_NOTE
            self.crisis = False
        req = LLMRequest(
            model=model,
            system=system,
            messages=[*history, ChatMessage("user", note)],
            max_tokens=services.HOST_MAX_TOKENS,
            effort="low",
            web_search=web,
        )
        parts: list[str] = []
        final = None
        searched = False
        out = OutputFilter()
        await self.send_json({"type": "start"})
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
                if piece := out.feed(ev.delta):
                    parts.append(piece)
                    await self.send_json({"type": "delta", "text": piece})
            if tail := out.flush():
                parts.append(tail)
                await self.send_json({"type": "delta", "text": tail})
        except asyncio.CancelledError:
            await finish(provider, self.user)
            await database_sync_to_async(services.after_turn)(
                self.sid, "".join(parts).strip(), after, cancelled=True
            )
            await self.send_json({"type": "done", "stop_reason": "cancelled"})
            raise
        except LLMError as e:
            await finish(provider, self.user)
            log.warning("workshop turn failed: %s", e.code)
            await self.send_json({"type": "error", "code": e.code, "retryable": e.retryable})
            return
        await finish(provider, self.user)
        if web:
            await database_sync_to_async(note_search)(self.user, searched, final)
        reply = "".join(parts).strip()
        if final and final.stop_reason == "refusal" and not reply:
            reply = "Let's keep going with the workshop. Tell me where you are."
        changed = await database_sync_to_async(services.after_turn)(self.sid, reply, after)
        stop = stop_reason(final.stop_reason if final else None)
        # Web pages from the search tool's results, never links the model wrote.
        sources = (final.sources if final and web else None) or []
        await self.send_json(
            {"type": "done", "stop_reason": stop, **({"sources": sources} if sources else {})}
        )
        await self._progress_if(changed)
        chips = await database_sync_to_async(services.suggest)(self.sid, stop)
        await self.send_json({"type": "suggest", "chips": chips})
        self._quiet_since = time.monotonic()
        await self._tile()

    async def _progress_if(self, changed: bool):
        """After `done`: the item just explained unlocks Next."""
        if changed:
            await self.send_json(
                {"type": "progress", "session": await database_sync_to_async(_session)(self.sid)}
            )

    # ── clock ────────────────────────────────────────────────────────
    async def _clock(self):
        try:
            while True:
                await asyncio.sleep(CLOCK_EVERY)
                if (
                    not await self.still_allowed()
                ):  # a quiet session still notices a revoked account or feature
                    return
                await self._pace()
        except asyncio.CancelledError:
            pass

    async def _pace(self):
        await self._tile()
        p, announce = await database_sync_to_async(services.tick)(self.sid)
        if not p:
            return
        await self.send_json({"type": "pace", **p})
        # Said once by the host at the planned end; if a reply is streaming, the next tick tries again.
        if announce and not self._busy() and await database_sync_to_async(services.claim_grace)(self.sid):
            note = await database_sync_to_async(services.grace_note)(self.sid)
            self._spawn(note, None, learner=False)
            return
        # A quiet learner gets one gentle "Still with me?" per item: never a cutoff, never repeated.
        if not self._busy() and time.monotonic() - self._quiet_since >= QUIET_AFTER:
            note = await database_sync_to_async(services.claim_check_in)(self.sid)
            if note:
                self._spawn(note, None, learner=False)


# ── Live faculty monitor ─────────────────────────────────────────────

MONITOR_RECHECK = 30.0
NUDGES_PER_MINUTE = 20


def _monitor_access(user_id, run_id) -> dict:
    """Re-run on connect, on every re-auth and every MONITOR_RECHECK seconds. → {"code": ...} when refused, else
    {"run": WorkshopRun, "scope": set of visible learner ids | None (everyone), "role": ...}.

    Org runs only (public and test runs have no dashboard); the viewer must be a manager or above of the run's org
    (perms.require), the org's `workshops` feature must be on, and a teacher sees only learners in their classes."""
    from django.http import Http404
    from rest_framework.exceptions import PermissionDenied

    from apps.accounts.models import User

    from .org import FeatureOff, scope_user_ids, staff

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user:
        return {"code": "unauthorized"}
    run = WorkshopRun.objects.select_related("org", "workshop").filter(pk=run_id).first()
    if not run:
        return {"code": "not_found"}
    if run.audience != WorkshopRun.Audience.ORG or not run.org_id:
        return {"code": "no_monitor"}
    try:
        me = staff(user, run.org.slug, "manager")
    except (Http404, PermissionDenied):
        return {"code": "forbidden"}
    except FeatureOff:
        return {"code": "feature_off"}
    return {"run": run, "scope": scope_user_ids(me), "role": me.role}


def _snapshot(run_id, scope) -> dict:
    from apps.orgs.models import Membership

    from .models import WorkshopEnrollment

    run = WorkshopRun.objects.get(pk=run_id)
    at = services.now()
    members = {m.user_id: m for m in Membership.objects.filter(org_id=run.org_id)}
    sessions = list(
        WorkshopSession.objects.filter(run_id=run_id)
        .select_related("run__workshop", "user__profile")
        .order_by("id")
    )
    sessions = [s for s in sessions if scope is None or s.user_id in scope]
    joined = {s.user_id for s in sessions}
    absent = [
        e.user
        for e in WorkshopEnrollment.objects.filter(run_id=run_id)
        .select_related("user__profile")
        .order_by("id")
        if e.user_id not in joined and (scope is None or e.user_id in scope)
    ]
    return {
        "run": {
            "id": run.id,
            "title": run.workshop.title,
            "starts_at": run.starts_at.isoformat(),
            "status": run.effective_status(at),
            "proctoring": run.effective_proctoring,
        },
        "tiles": [monitor.tile(s, at, members.get(s.user_id)) for s in sessions],
        "not_joined": [monitor.learner_out(u, members.get(u.id)) for u in absent],
    }


def _session_in_scope(run_id, session_id, scope) -> bool:
    try:
        sid = int(session_id)
    except (TypeError, ValueError):
        return False
    s = WorkshopSession.objects.filter(pk=sid, run_id=run_id).only("user_id").first()
    return bool(s) and (scope is None or s.user_id in scope)


class MonitorConsumer(SocketAuth, AsyncJsonWebsocketConsumer):
    """/ws/workshop-runs/<run_id>/monitor/ — the institution's live dashboard for one org run.

    Client → server: auth{token} · nudge{session_id, text ≤300} · ack_hand{session_id}.
    Server → client: ready{run, scope} · snapshot{run, tiles, not_joined} · tile{tile} · ack{action, session_id}
    · error{code}. Close codes: 4401 (token), 4403 (not allowed: not staff, other org, public/test run, feature off),
    4404 (no such run)."""

    feature = ""  # the org feature is checked in _monitor_access

    async def connect(self):
        self.run_id = self.scope["url_route"]["kwargs"]["run_id"]
        self.visible: set | None = set()
        self.joined = False
        self.watch: asyncio.Task | None = None
        await self.accept()

    async def disconnect(self, code):
        if self.watch:
            self.watch.cancel()
        if self.joined:
            await self.channel_layer.group_discard(monitor.group_name(self.run_id), self.channel_name)

    async def _authorize(self) -> bool:
        """Access and scope from the database; closes the socket when refused."""
        res = await database_sync_to_async(_monitor_access)(self.user.pk, self.run_id)
        if code := res.get("code"):
            self.visible = set()
            await self.send_json({"type": "error", "code": code})
            await self.close(code=4401 if code == "unauthorized" else 4404 if code == "not_found" else 4403)
            return False
        self.visible = res["scope"]
        return True

    async def _send_snapshot(self):
        snap = await database_sync_to_async(_snapshot)(self.run_id, self.visible)
        await self.send_json({"type": "snapshot", **snap})

    async def reauth(self, token: str):
        """Same account renewing its token: access and scope are checked again, then a fresh snapshot."""
        from apps.mentor.auth import user_from_token

        user = await user_from_token(token or "")
        if not user or user.pk != self.user.pk:
            await self.send_json({"type": "error", "code": "already_authenticated"})
            return
        self.exp = _token_exp(token)
        if await self._authorize():
            await self.send_json({"type": "ready", "scope": "all" if self.visible is None else "classes"})
            await self._send_snapshot()

    async def receive_json(self, content, **kwargs):
        kind = content.get("type") if isinstance(content, dict) else None
        if kind == "auth":
            if self.user:
                await self.reauth(content.get("token") or "")
                return
            if not await self.authenticate(content.get("token") or ""):
                await self.send_json({"type": "error", "code": "unauthorized"})
                await self.close(code=4401)
                return
            if not await self._authorize():
                return
            await self.channel_layer.group_add(monitor.group_name(self.run_id), self.channel_name)
            self.joined = True
            await self.send_json({"type": "ready", "scope": "all" if self.visible is None else "classes"})
            await self._send_snapshot()
            self.watch = asyncio.create_task(self._recheck())
            return
        if not self.user:
            await self.send_json({"type": "error", "code": "unauthorized"})
            return
        if await self.expired():
            return
        if kind not in ("nudge", "ack_hand"):
            await self.send_json({"type": "error", "code": "unknown_type"})
            return
        # Every action re-checks access and scope from the database first (a demoted teacher can't act).
        if not await self._authorize():
            return
        sid = content.get("session_id")
        if not await database_sync_to_async(_session_in_scope)(self.run_id, sid, self.visible):
            await self.send_json({"type": "error", "code": "not_in_scope", "session_id": sid})
            return
        sid = int(sid)
        if kind == "nudge":
            text, code = monitor.clean_nudge(content.get("text"))
            if code:
                await self.send_json({"type": "error", "code": code, "session_id": sid})
                return
            if not await database_sync_to_async(self._nudge_allowed)():
                await self.send_json({"type": "error", "code": "rate_limited", "session_id": sid})
                return
            await database_sync_to_async(monitor.nudge)(sid, self.user, text)
            await self.send_json({"type": "ack", "action": "nudge", "session_id": sid})
            return
        raised = await database_sync_to_async(monitor.ack_hand)(sid, self.user)
        await self.send_json({"type": "ack", "action": "ack_hand", "session_id": sid, "changed": raised})
        if raised:
            await monitor.apublish(sid, urgent=True)

    def _nudge_allowed(self) -> bool:
        from django.core.cache import cache

        key = f"wsrun:nudges:{self.user.pk}"
        cache.add(key, 0, 60)
        try:
            return cache.incr(key) <= NUDGES_PER_MINUTE
        except ValueError:
            return True

    async def wsrun_tile(self, event):
        """A learner's tile from the run's group: only learners in this viewer's scope get through."""
        t = event.get("tile") or {}
        if not self.user or time.time() > self.exp:
            return
        if self.visible is not None and (t.get("learner") or {}).get("id") not in self.visible:
            return
        await self.send_json({"type": "tile", "tile": t})

    async def _recheck(self):
        try:
            while True:
                await asyncio.sleep(MONITOR_RECHECK)
                if await self.expired() or not await self._authorize():
                    return
        except asyncio.CancelledError:
            pass
