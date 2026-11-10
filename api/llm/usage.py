"""Token metering for every AI call made through router.resolve().

The wrapper only *collects* usage while streaming (no DB in async code). Callers write it with flush_usage():
sync callers right after asyncio.run(), async consumers via database_sync_to_async — so the DB write always
happens on a normal Django thread."""

from contextvars import ContextVar

from .base import LLMError, LLMRequest

# Set by the JWT authentication class for REST requests, so background-free sync calls know who to attribute.
current_user_id: ContextVar[int | None] = ContextVar("aasan_llm_user", default=None)


class Metered:
    def __init__(self, inner, task: str, model: str):
        self.inner, self.task, self.model = inner, task, model
        self.name = inner.name
        self.events: list[dict] = []

    async def stream(self, req: LLMRequest):
        try:
            async for ev in self._stream(req):
                yield ev
        except LLMError as e:
            from config.metrics import count

            count("llm_errors", provider=self.inner.name, code=e.code)
            raise

    async def _stream(self, req: LLMRequest):
        async for ev in self.inner.stream(req):
            if ev.done:
                u = ev.usage or {}
                self.events.append(
                    {
                        "provider": self.inner.name,
                        "model": ev.model or req.model,
                        "in": int(u.get("input_tokens") or 0),
                        "out": int(u.get("output_tokens") or 0),
                        "cached": int(u.get("cache_read_input_tokens") or 0),
                    }
                )
            yield ev

    async def complete(self, req: LLMRequest) -> str:
        if self.inner.name == "fake":  # demo/test provider: instant, no real tokens
            self.events.append({"provider": "fake", "model": "fake", "in": 0, "out": 0, "cached": 0})
            return await self.inner.complete(req)
        chunks = []
        async for ev in self.stream(req):
            if ev.done and ev.stop_reason == "refusal":
                raise LLMError("refusal")
            chunks.append(ev.delta)
        return "".join(chunks)

    async def aclose(self):
        close = getattr(self.inner, "aclose", None)
        if close:
            await close()


def flush_usage(provider, user=None) -> int:
    """Write collected usage rows (sync, Django thread). Safe to call on any provider."""
    events = getattr(provider, "events", None)
    if not events:
        return 0
    from apps.providers.models import LLMUsage

    uid = getattr(user, "id", None) or current_user_id.get()
    if uid:
        from django.contrib.auth import get_user_model

        if not get_user_model().objects.filter(pk=uid).exists():  # stale id (deleted account) → unattributed
            uid = None
    rows = [
        LLMUsage(
            user_id=uid,
            task=provider.task,
            provider=e.get("provider") or provider.name,
            model=e["model"][:80],
            input_tokens=e["in"],
            output_tokens=e["out"],
            cached_tokens=e["cached"],
        )
        for e in events
    ]
    try:
        LLMUsage.objects.bulk_create(rows)
    except Exception:  # metering must never break a lesson or a chat
        import logging

        logging.getLogger(__name__).warning("could not record LLM usage", exc_info=True)
        return 0
    provider.events = []
    return len(rows)


async def finish(provider, user=None):
    """Async callers: close the provider, then record its usage on a Django thread."""
    from channels.db import database_sync_to_async

    from .router import aclose

    await aclose(provider)
    await database_sync_to_async(flush_usage)(provider, user)
