"""Regression: async provider clients are bound to the event loop that created
their connections. Sync jobs run each call in a fresh asyncio.run() loop, so a
cached client crashed with 'Event loop is closed' on the next job."""

import asyncio

import pytest

from apps.providers.models import ProviderConfig
from llm import router
from llm.base import StreamEvent
from llm.prompts.curriculum import OpenGrade
from llm.structured import complete_json_sync


class LoopBoundProvider:
    """Mimics httpx pools: remembers the loop it first ran on."""

    name = "loopbound"
    instances = []

    def __init__(self):
        self.loop = None
        self.closed = False
        LoopBoundProvider.instances.append(self)

    async def stream(self, req):
        loop = asyncio.get_running_loop()
        if self.closed:
            raise RuntimeError("used after close")
        if self.loop is not None and self.loop is not loop:
            raise RuntimeError("Event loop is closed")
        self.loop = loop
        yield StreamEvent(delta='{"score": 1.0, "feedback": "ok"}')
        yield StreamEvent(done=True, stop_reason="end_turn")

    async def complete(self, req):
        return "".join([e.delta async for e in self.stream(req)])

    async def aclose(self):
        self.closed = True


@pytest.fixture
def loopbound(settings, monkeypatch, db):
    settings.LLM_FORCE_PROVIDER = ""
    ProviderConfig.objects.create(capability="utility", provider="fake", model="m")
    LoopBoundProvider.instances.clear()
    monkeypatch.setattr(router, "_build", lambda name, key: LoopBoundProvider())


def test_sequential_sync_calls_use_fresh_clients(loopbound):
    for _ in range(3):  # each call = new event loop; must not crash
        assert complete_json_sync("grade", "s", "u", OpenGrade).score == 1.0
    assert len(LoopBoundProvider.instances) == 3
    assert all(p.closed for p in LoopBoundProvider.instances)  # connections released


def test_resolve_returns_new_instance_each_time(loopbound):
    a, _ = router.resolve("grade")
    b, _ = router.resolve("grade")
    assert a is not b
