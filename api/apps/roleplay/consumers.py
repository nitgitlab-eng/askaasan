"""/ws/roleplay/ — the AI character's replies stream token by token."""

import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.mentor.consumers import SocketAuth
from apps.mentor.websearch import count_search, note_search, search_allowed
from llm.base import ChatMessage, LLMError, LLMRequest
from llm.guard import OutputFilter, screen_turn
from llm.prompts.guardrails import CRISIS_NOTE, search_note
from llm.prompts.roleplay import character_system
from llm.router import resolve
from llm.usage import finish

from .models import RolePlaySession, RolePlayTurn

log = logging.getLogger(__name__)
MAX_INPUT = 1500


async def _feature_blocked(user, feature: str) -> str | None:
    from channels.db import database_sync_to_async

    from apps.orgs.extras import refusal

    return await database_sync_to_async(refusal)(user, feature)


class RolePlayConsumer(SocketAuth, AsyncJsonWebsocketConsumer):
    feature = "roleplay"
    _task: asyncio.Task | None = None

    async def connect(self):
        await self.accept()

    async def disconnect(self, code):
        if self._task and not self._task.done():
            self._task.cancel()

    async def receive_json(self, content, **kwargs):
        if content.get("type") == "auth":
            if self.user:
                await self.reauth(content.get("token") or "")
                return
            await self.authenticate(content.get("token") or "")
            if self.user and (code := await _feature_blocked(self.user, "roleplay")):
                self.user = None
                await self.send_json({"type": "error", "code": code})
                return
            await self.send_json(
                {"type": "ready"} if self.user else {"type": "error", "code": "unauthorized"}
            )
            return
        if not self.user:
            await self.send_json({"type": "error", "code": "unauthorized"})
            return
        if await self.expired():
            return
        if content.get("type") == "message":
            if self._task and not self._task.done():
                await self.send_json({"type": "error", "code": "busy"})
                return
            if not await self.still_allowed():
                return
            self._task = self.spawn(self._reply(content))
        elif content.get("type") == "cancel" and self._task:
            self._task.cancel()

    @database_sync_to_async
    def _prepare(self, session_id, text):
        s = (
            RolePlaySession.objects.filter(id=session_id, user=self.user, status="active")
            .select_related("scenario")
            .first()
        )
        if not s:
            return None, None, "not_found"
        if s.learner_turns >= s.scenario.max_turns:
            return None, None, "turn_limit"
        from apps.providers.services import BudgetExceeded

        from .services import charge_ai

        try:
            charge_ai(self.user)
        except BudgetExceeded:
            return None, None, "ai_budget_exceeded"
        RolePlayTurn.objects.create(session=s, role=RolePlayTurn.Role.LEARNER, text=text)
        provider, model = resolve("tutor")
        history = [ChatMessage("user" if t.role == "learner" else "assistant", t.text) for t in s.turns.all()]
        # The API needs a user turn first; the character's opening line becomes context.
        if history and history[0].role == "assistant":
            history.insert(0, ChatMessage("user", "(The conversation begins.)"))
        return s, (provider, model, history), None

    @database_sync_to_async
    def _save(self, s, text):
        t = RolePlayTurn.objects.create(session=s, role=RolePlayTurn.Role.CHARACTER, text=text)
        return s.scenario.max_turns - s.learner_turns, t.id

    async def _reply(self, content):
        text = (content.get("text") or "").strip()[:MAX_INPUT]
        if not text:
            return
        screened = await database_sync_to_async(screen_turn)(text, self.user.pk, "roleplay")
        text = screened.text  # secrets masked before the model and the transcript
        try:
            s, prep, err = await self._prepare(content.get("session_id"), text)
        except LLMError as e:
            await self.send_json({"type": "error", "code": e.code})
            return
        if err:
            await self.send_json({"type": "error", "code": err})
            return
        provider, model, history = prep
        # The character can look up real-world facts (today's prices, timings, news) but stays in the scene.
        web = await database_sync_to_async(search_allowed)(self.user)
        system = (
            character_system(s.scenario, s.language, self.user)
            + search_note(web, kind="roleplay")
            + (CRISIS_NOTE if screened.crisis else "")
        )
        await self.send_json({"type": "start"})
        parts, final, searched = [], None, False
        out = OutputFilter()
        try:
            async for ev in provider.stream(
                LLMRequest(
                    model=model, system=system, messages=history, max_tokens=600, effort="low", web_search=web
                )
            ):
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
            raise
        except LLMError as e:
            await finish(provider, self.user)
            await self.send_json({"type": "error", "code": e.code})
            return
        await finish(provider, self.user)
        if web:
            await database_sync_to_async(note_search)(self.user, searched, final)
        left, turn_id = await self._save(s, "".join(parts).strip())
        # Web pages from the search tool's results, never links the model wrote.
        sources = (final.sources if final and web else None) or []
        await self.send_json({"type": "done", "turns_left": left, "turn_id": turn_id, "sources": sources})
