"""/ws/assistant/ — streams the mentor's reply token by token and emits
mascot cues so the on-screen companion reacts in real time."""

import asyncio
import json
import logging
import re
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.accounts.preferences import upgrade
from llm.base import ChatMessage, LLMError, LLMRequest
from llm.guard import OutputFilter, screen_turn
from llm.prompts.guardrails import CRISIS_NOTE, search_note
from llm.prompts.tutor import SPOKEN_TURN_NOTE, build_document_context, build_tutor_system
from llm.router import resolve
from llm.usage import finish

from .auth import user_from_token
from .models import Conversation, Message
from .websearch import asks_for_web, count_search, note_search, search_allowed

log = logging.getLogger(__name__)
HISTORY_LIMIT = 30
MAX_INPUT_CHARS = 4000
# Shown when the model refuses without saying anything; in the learner's language (other languages fall back to English).
REFUSAL = {
    "en": "Sorry, I can't help with that. Shall we learn something else?",
    "ta": "மன்னிக்கவும், அதற்கு என்னால் உதவ முடியாது. வேறு ஏதாவது கற்றுக்கொள்ளலாமா?",
    "tanglish": "Sorry, adhukku ennala help panna mudiyadhu. Vera edhavadhu kathukkalaamaa?",
    "hi": "माफ़ कीजिए, मैं इसमें मदद नहीं कर सकता। क्या हम कुछ और सीखें?",
}


def _id(v) -> int | None:
    """A client-sent id as an int, or None when missing or malformed (a bad id must not crash the reply task)."""
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _refusal(user) -> str:
    from apps.learning.services import content_language

    return REFUSAL.get(content_language(user), REFUSAL["en"])


def _nudges(user):
    from apps.game.services import nudges

    return nudges(user)


async def _feature_blocked(user, feature: str) -> str | None:
    """The refusal code (truthy) when `user` can't use `feature`, else None."""
    from channels.db import database_sync_to_async

    from apps.orgs.extras import refusal

    return await database_sync_to_async(refusal)(user, feature)


def _refund_message(user_id):
    """Give back the mentor message just consumed: a reply that failed before any text arrived isn't counted (R50)."""
    from apps.billing.models import UsageEvent

    ev = UsageEvent.objects.filter(user_id=user_id, metric="mentor_message").order_by("-id").first()
    if ev:
        ev.delete()


def _token_exp(token: str) -> float:
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import AccessToken

    try:
        return float(AccessToken(token)["exp"])
    except (TokenError, KeyError, TypeError, ValueError):
        return 0.0


def _revoked(user_id, feature: str) -> str | None:
    from apps.accounts.models import User
    from apps.orgs.extras import refusal

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user:
        return "unauthorized"
    return refusal(user, feature)


RETRY_DELAY = 1.5  # seconds before the one retry of a retryable AI error
AUTH_TIMEOUT = 10.0  # seconds an open socket may wait for its auth message before it is closed


class SocketAuth:
    """Shared by the mentor, role-play and live sockets: one identity per socket, and the token's expiry, the
    account and the school's feature switch keep being checked while the socket stays open (H97/H99)."""

    user = None
    exp = 0.0
    feature = ""
    _auth_watch: asyncio.Task | None = None

    async def websocket_connect(self, message):
        await super().websocket_connect(message)
        self._auth_watch = asyncio.create_task(self._close_if_never_authenticated())

    async def _close_if_never_authenticated(self):
        """Sockets are accepted before the token arrives; one that never sends it doesn't get to hold a slot."""
        await asyncio.sleep(AUTH_TIMEOUT)
        if self.user is None:
            try:
                await self.send(text_data=json.dumps({"type": "error", "code": "unauthorized"}))
                await self.close(code=4401)
            except Exception:  # noqa: BLE001 - already gone
                log.debug("auth timeout: socket already closed")

    async def websocket_disconnect(self, message):
        if self._auth_watch:
            self._auth_watch.cancel()
        await super().websocket_disconnect(message)

    def spawn(self, coro):
        """Run a reply/turn in the background without ever leaving the client waiting: an unexpected error (a DB error
        while saving, say) is logged and reported as `server_error` instead of dying silently in a dropped task."""
        return asyncio.create_task(self._guarded(coro))

    async def _guarded(self, coro):
        try:
            return await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if "Disconnect" in type(e).__name__:  # the learner left mid-reply; nothing to tell them
                log.debug("socket closed during a %s task", type(self).__name__)
                return None
            log.exception("%s task failed", type(self).__name__)
            try:
                await self.send_json({"type": "error", "code": "server_error", "retryable": True})
            except Exception:  # noqa: BLE001 - the socket may be gone too
                log.debug("could not report the failure; socket already closed")
            return None

    async def authenticate(self, token: str):
        self.user = await user_from_token(token or "")
        self.exp = _token_exp(token or "") if self.user else 0.0
        return self.user

    async def reauth(self, token: str):
        """An auth message on an authenticated socket: the same account may renew its token (a long live class
        outlives one access token); any other account is refused, so turns stay billed to the first one."""
        user = await user_from_token(token or "")
        if user and user.pk == self.user.pk:
            self.exp = _token_exp(token)
            await self.send_json({"type": "ready"})
        else:
            await self.send_json({"type": "error", "code": "already_authenticated"})

    async def expired(self) -> bool:
        if time.time() <= self.exp:
            return False
        await self.send_json({"type": "error", "code": "token_expired"})
        await self.close(code=4401)
        return True

    async def still_allowed(self) -> bool:
        """Before each AI turn: token unexpired, account still active, feature still on (closes the socket if not)."""
        if await self.expired():
            return False
        code = await database_sync_to_async(_revoked)(self.user.pk, self.feature)
        if not code:
            return True
        await self.send_json({"type": "error", "code": code})
        await self.close(code=4401 if code == "unauthorized" else 4403)
        return False


class AssistantConsumer(SocketAuth, AsyncJsonWebsocketConsumer):
    feature = "mentor"
    _task: asyncio.Task | None = None

    async def connect(self):
        await self.accept()

    async def disconnect(self, code):
        if self._task and not self._task.done():
            self._task.cancel()

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
            if code := await _feature_blocked(self.user, "mentor"):
                await self.send_json({"type": "error", "code": code})
                await self.close(code=4403)
                return
            await self.send_json({"type": "ready"})
            for n in await database_sync_to_async(_nudges)(self.user):
                await self.send_json({"type": "nudge", **n})
            return
        if not self.user:
            await self.send_json({"type": "error", "code": "unauthorized"})
            return
        if await self.expired():
            return
        if kind == "message":
            if self._task and not self._task.done():
                await self.send_json({"type": "error", "code": "busy"})
                return
            if not await self.still_allowed():
                return
            self._task = self.spawn(self._reply(content))
        elif kind == "cancel" and self._task:
            self._task.cancel()

    @database_sync_to_async
    def _prepare(self, conversation_id, text, document_id=None):
        """→ (conversation, history), or (None, error code)."""
        from apps.orgs.extras import viewable_documents

        if conversation_id:
            conv = Conversation.objects.filter(id=conversation_id, user=self.user).first()
            if not conv:
                return None, "not_found"
            # Re-check every turn: access to an org document can be revoked after the conversation started.
            if conv.document_id and not viewable_documents(self.user).filter(id=conv.document_id).exists():
                return None, "document_unavailable"
        else:
            doc = None
            if document_id:
                doc = (
                    viewable_documents(self.user).filter(id=document_id).first()
                )  # own notes or notes shared by my org
                if not doc:
                    return None, "not_found"
            conv = Conversation.objects.create(
                user=self.user,
                title=text[:80],
                document=doc,
                kind=Conversation.Kind.DOCUMENT if doc else Conversation.Kind.ASSISTANT,
            )
        Message.objects.create(conversation=conv, role=Message.Role.USER, content=text)
        history = list(conv.messages.order_by("-created_at")[:HISTORY_LIMIT])[::-1]
        return conv, [ChatMessage(role=m.role, content=m.content) for m in history]

    @database_sync_to_async
    def _sources(self, conv, question):
        if not conv.document_id:
            return []
        from apps.docs.search import top_chunks

        return [
            {"chunk_id": c.id, "page": c.page, "text": c.text}
            for c in top_chunks(conv.document, question, k=6)
        ]

    @database_sync_to_async
    def _save_reply(self, conv, text, final, citations=None):
        msg = Message.objects.create(
            conversation=conv,
            role=Message.Role.ASSISTANT,
            content=text,
            citations=citations or [],
            stop_reason=(final.stop_reason or "") if final else "cancelled",
            model=(final.model or "") if final else "",
            usage=final.usage if final else {},
        )
        conv.save(update_fields=["updated_at"])
        return msg.id

    async def _reply(self, content):
        text = (content.get("text") or "").strip()[:MAX_INPUT_CHARS]
        if not text:
            await self.send_json({"type": "error", "code": "empty"})
            return
        # Secrets are masked before the words reach the model, a web search or the database.
        screened = await database_sync_to_async(screen_turn)(text, self.user.pk, "mentor")
        text = screened.text
        from apps.billing.services import PlanLimit, check

        try:
            await database_sync_to_async(check)(self.user, "mentor_messages_per_day")
        except PlanLimit as e:
            await self.send_json({"type": "error", "retryable": False, **e.payload()})
            return
        conv_id, doc_id = content.get("conversation_id"), content.get("document_id")
        if (conv_id and _id(conv_id) is None) or (doc_id and _id(doc_id) is None):
            await self.send_json({"type": "error", "code": "not_found"})
            return
        conv, history = await self._prepare(_id(conv_id), text, _id(doc_id))
        if not conv:
            await self.send_json({"type": "error", "code": history})
            return

        prefs = upgrade(self.user.preferences.data)
        system = build_tutor_system(self.user.profile, prefs, prefs["mascot"]["name"])
        sources = await self._sources(conv, text)
        if sources:
            system += build_document_context(sources)
        # Live web search: always offered in chat, voice and Lesson Ask; in Documents only when they ask for the web.
        web = (not conv.document_id or asks_for_web(text)) and await database_sync_to_async(search_allowed)(
            self.user
        )
        system += search_note(web)
        if screened.crisis:
            system += CRISIS_NOTE
        if content.get("via") == "voice":  # a spoken question gets a reply shaped for listening
            system += SPOKEN_TURN_NOTE
        try:
            provider, model = await database_sync_to_async(resolve)("tutor")
        except LLMError as e:
            await self.send_json({"type": "error", "code": e.code, "retryable": False})
            await self.send_json({"type": "mascot", "state": "confused"})
            return
        from apps.billing.services import consume

        try:  # counted only once a reply is really coming; atomic check+record so parallel sockets can't overshoot
            await database_sync_to_async(consume)(self.user, "mentor_messages_per_day", "mentor_message")
        except PlanLimit as e:
            await self.send_json({"type": "error", "retryable": False, **e.payload()})
            return
        req = LLMRequest(
            model=model, system=system, messages=history, max_tokens=8000, effort="low", web_search=web
        )

        await self.send_json({"type": "start", "conversation_id": conv.id})
        await self.send_json({"type": "mascot", "state": "thinking"})
        parts, final, started, searched = [], None, False, False

        async def say(piece: str) -> None:
            nonlocal started
            if not piece:
                return
            if not started:
                started = True
                await self.send_json({"type": "mascot", "state": "talking"})
            parts.append(piece)
            await self.send_json({"type": "delta", "text": piece})

        try:
            for attempt in (1, 2):
                out = OutputFilter()  # no images, and no links the model wrote itself
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
                                await self.send_json({"type": "mascot", "state": "thinking"})
                            continue
                        await say(out.feed(ev.delta))
                    await say(out.flush())
                    break
                except LLMError as e:
                    # A brief overload or rate limit before any words arrived (e.g. a new user's first question while
                    # their first course is being built on the same AI key): wait a moment and try once more.
                    if attempt == 1 and e.retryable and not parts:
                        log.info("tutor stream retrying after %s", e.code)
                        await asyncio.sleep(RETRY_DELAY)
                        continue
                    raise
        except asyncio.CancelledError:
            await finish(provider, self.user)
            await self._save_reply(conv, "".join(parts), None)
            await self.send_json({"type": "done", "stop_reason": "cancelled"})
            await self.send_json({"type": "mascot", "state": "idle"})
            raise
        except LLMError as e:
            await finish(provider, self.user)
            log.warning("tutor stream failed: %s", e.code)
            if not parts:  # nothing reached the learner, so the message doesn't count against the daily limit
                await database_sync_to_async(_refund_message)(self.user.pk)
            await self.send_json({"type": "error", "code": e.code, "retryable": e.retryable})
            await self.send_json({"type": "mascot", "state": "confused"})
            return

        await finish(provider, self.user)
        if web:  # providers that report sources but no "searching" event still count
            await database_sync_to_async(note_search)(self.user, searched, final)
        reply = "".join(parts)
        if final and final.stop_reason == "refusal":
            reply = reply or await database_sync_to_async(_refusal)(self.user)
        cited = sorted({int(n) for n in re.findall(r"\[(\d{1,2})\]", reply) if 1 <= int(n) <= len(sources)})
        from apps.docs.search import best_snippet

        def citing_text(n):  # the reply sentences that cite [n] — what the snippet should support
            return " ".join(s for s in re.split(r"(?<=[.!?])\s+|\n", reply) if f"[{n}]" in s) or text

        citations = [
            {
                "n": n,
                "page": sources[n - 1]["page"],
                "chunk_id": sources[n - 1]["chunk_id"],
                "snippet": best_snippet(sources[n - 1]["text"], citing_text(n)),
            }
            for n in cited
        ]
        # Web pages the reply used (from the provider's search results, never from the model's text).
        citations += [{"kind": "web", **src} for src in ((final.sources if final and web else None) or [])]
        msg_id = await self._save_reply(conv, reply, final, citations)
        await self.send_json(
            {
                "type": "done",
                "message_id": msg_id,
                "stop_reason": final.stop_reason if final else None,
                "citations": citations,
            }
        )
        await self.send_json({"type": "mascot", "state": "idle"})
