"""LLM failover (llm/router.py): a provider that is rate-limited or down before any text hands over to LLM_FALLBACK."""

import asyncio

import pytest

from llm import router
from llm.base import ChatMessage, LLMError, LLMRequest, StreamEvent
from llm.usage import flush_usage


class Stub:
    def __init__(self, name, fail=None, after_text=False):
        self.name, self.fail, self.after_text, self.calls = name, fail, after_text, 0

    async def stream(self, req):
        self.calls += 1
        if self.fail and self.after_text:
            yield StreamEvent(delta="partial ")
        if self.fail:
            raise self.fail
        yield StreamEvent(delta=f"from {self.name} ({req.model})")
        yield StreamEvent(done=True, usage={"input_tokens": 3, "output_tokens": 4}, model=req.model)

    async def complete(self, req):
        return "".join([e.delta async for e in self.stream(req)])

    async def aclose(self):
        pass


@pytest.fixture
def stubs(settings, monkeypatch, db):
    settings.LLM_FORCE_PROVIDER = ""
    settings.LLM_FALLBACK = "gemini"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    made = {}

    def build(name, key):
        made[name] = made.get(name) or Stub(name)
        return made[name]

    monkeypatch.setattr(router, "_build", build)
    return made


def _req(model):
    return LLMRequest(model=model, system="s", messages=[ChatMessage(role="user", content="hi")])


async def _text(p, model):
    return "".join([e.delta async for e in p.stream(_req(model))])


def test_rate_limited_provider_hands_over_and_is_skipped_for_a_while(stubs):
    stubs["anthropic"] = Stub("anthropic", fail=LLMError("rate_limited", retryable=True))
    p, model = router.resolve("grade")
    out = asyncio.run(_text(p, model))
    assert out.startswith("from gemini")
    assert flush_usage(p) == 1  # the backup's tokens are recorded under its own name
    from apps.providers.models import LLMUsage

    assert LLMUsage.objects.get().provider == "gemini"
    p2, model2 = router.resolve("grade")
    assert asyncio.run(_text(p2, model2)).startswith("from gemini")
    assert stubs["anthropic"].calls == 1  # the breaker skipped it the second time


def test_non_retryable_errors_and_mid_reply_failures_are_not_switched(stubs):
    stubs["anthropic"] = Stub("anthropic", fail=LLMError("refusal"))
    p, model = router.resolve("grade")
    with pytest.raises(LLMError):
        asyncio.run(_text(p, model))
    stubs["anthropic"] = Stub("anthropic", fail=LLMError("rate_limited", retryable=True), after_text=True)
    p, model = router.resolve("grade")
    with pytest.raises(LLMError):
        asyncio.run(_text(p, model))


def test_no_fallback_configured_returns_the_plain_provider(stubs, settings):
    settings.LLM_FALLBACK = ""
    p, _ = router.resolve("grade")
    assert not isinstance(p, router.Failover)


def test_spend_alert_mails_once_per_threshold(db, settings, mailoutbox):
    from decimal import Decimal

    from apps.providers.models import LLMUsage, ModelPrice
    from apps.providers.tasks import spend_check

    settings.ADMINS = [("Staff", "staff@example.test")]
    settings.LLM_MONTHLY_BUDGET = 100
    ModelPrice.objects.create(
        provider="anthropic", model="m", input_per_m=Decimal(0), output_per_m=Decimal(1_000_000)
    )
    LLMUsage.objects.create(task="grade", provider="anthropic", model="m", input_tokens=0, output_tokens=60)
    assert spend_check()["pct"] == 60.0
    assert spend_check()["pct"] == 60.0
    assert len(mailoutbox) == 1 and "50%" in mailoutbox[0].subject
    LLMUsage.objects.create(task="grade", provider="anthropic", model="m", input_tokens=0, output_tokens=30)
    spend_check()
    assert len(mailoutbox) == 2 and "80%" in mailoutbox[1].subject
