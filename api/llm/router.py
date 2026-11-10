"""Resolve an LLM task to a provider instance + model.

Order: LLM_FORCE_PROVIDER (demo/tests) → admin console config (DB) → .env.

Every call builds a NEW provider. Async SDK clients pool connections that are
bound to the event loop that opened them; sync jobs run each request in a fresh
asyncio.run() loop, so a shared client crashes later calls with
"Event loop is closed". Callers close the provider when done (see aclose)."""

import logging

from django.conf import settings

from .base import LLMError, LLMRequest, Provider


def _build(name: str, key: str) -> Provider:
    if name == "anthropic":
        from .providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=key)
    if name == "openai":
        from .providers.openai_provider import OpenAIProvider

        return OpenAIProvider(api_key=key)
    if name == "gemini":
        from .providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=key)
    if name == "fake":
        from .providers.fake_provider import FakeProvider

        return FakeProvider()
    raise LLMError("unknown_provider", name)


def provider_for(cfg) -> Provider:
    if cfg.provider != "fake" and not cfg.key:
        raise LLMError("provider_not_configured", f"no API key for {cfg.provider}")
    return _build(cfg.provider, cfg.key)


def resolve(task: str) -> tuple[Provider, str]:
    from .usage import Metered

    if settings.LLM_FORCE_PROVIDER:
        return Metered(_build(settings.LLM_FORCE_PROVIDER, ""), task, "fake"), "fake"
    from apps.providers.catalog import TASK_CAPABILITY
    from apps.providers.services import resolve as resolve_config

    capability = TASK_CAPABILITY.get(task)
    if not capability:
        raise LLMError("unknown_task", task)
    cfg = resolve_config(capability)
    if not cfg.enabled:
        raise LLMError("provider_not_configured", f"{capability} is disabled")
    primary = Metered(provider_for(cfg), task, cfg.model)
    if backup := _backup(capability, cfg.provider):
        return Failover(primary, cfg.model, task, *backup), cfg.model
    return primary, cfg.model


# ── Failover ──
# LLM_FALLBACK names providers to try, in order, when the configured one answers 429/5xx/timeout before any text (a
# reply already streaming is never switched mid-way). A failing provider is skipped for LLM_BREAKER_SECONDS, so a
# provider outage costs one slow call per window, not one per learner.


def _down_key(name: str) -> str:
    return f"llm-down:{name}"


def is_down(name: str) -> bool:
    from django.core.cache import cache

    return bool(cache.get(_down_key(name)))


def mark_down(name: str) -> None:
    from django.core.cache import cache

    cache.set(_down_key(name), 1, settings.LLM_BREAKER_SECONDS)
    logging.getLogger(__name__).warning("LLM provider %s failing: using the fallback for a while", name)


def _key_for(name: str) -> str:
    import os

    from apps.providers.catalog import ENV_KEYS
    from apps.providers.models import ProviderConfig

    for row in ProviderConfig.objects.filter(provider=name).exclude(encrypted_key=""):
        if key := row.get_key():
            return key
    return os.getenv(ENV_KEYS.get(name, ""), "")


def _backup(capability: str, primary: str) -> tuple[str, str, str] | None:
    """(provider, model, key) of the first usable fallback for this capability, or None."""
    from apps.providers.catalog import CAPABILITIES

    spec = CAPABILITIES[capability]["providers"]
    for name in (n.strip() for n in settings.LLM_FALLBACK.split(",")):
        if not name or name == primary or name not in spec or is_down(name):
            continue
        if key := _key_for(name):
            return name, spec[name].get("default_model", ""), key
    return None


class Failover:
    """Looks like one metered provider; switches to the backup on a retryable error before any output."""

    def __init__(self, primary, primary_model: str, task: str, name: str, model: str, key: str):
        from dataclasses import replace

        from .usage import Metered

        self._replace = replace
        self.primary, self.primary_model, self.task = primary, primary_model, task
        self.backup = Metered(_build(name, key), task, model)
        self.backup_model = model
        self.name = primary.name

    @property
    def events(self) -> list[dict]:
        return self.primary.events + self.backup.events

    @events.setter
    def events(self, value):  # flush_usage clears both
        self.primary.events, self.backup.events = list(value), []

    def _for_backup(self, req: LLMRequest) -> LLMRequest:
        return self._replace(req, model=self.backup_model) if req.model == self.primary_model else req

    async def stream(self, req: LLMRequest):
        if not is_down(self.primary.name):
            started = False
            try:
                async for ev in self.primary.stream(req):
                    started = started or bool(ev.delta)
                    yield ev
                return
            except LLMError as e:
                if started or not e.retryable:
                    raise
                mark_down(self.primary.name)
        async for ev in self.backup.stream(self._for_backup(req)):
            yield ev

    async def complete(self, req: LLMRequest) -> str:
        if not is_down(self.primary.name):
            try:
                return await self.primary.complete(req)
            except LLMError as e:
                if not e.retryable:
                    raise
                mark_down(self.primary.name)
        return await self.backup.complete(self._for_backup(req))

    async def aclose(self):
        for p in (self.primary, self.backup):
            try:
                await p.aclose()
            except Exception:
                logging.getLogger(__name__).debug("provider close failed", exc_info=True)


async def aclose(provider) -> None:
    close = getattr(provider, "aclose", None)
    if close:
        try:
            await close()
        except Exception:
            logging.getLogger(__name__).debug("provider close failed", exc_info=True)


async def complete_once(provider: Provider, req: LLMRequest) -> str:
    """One completion, then release the client's connections on this loop."""
    try:
        return await provider.complete(req)
    finally:
        await aclose(provider)
