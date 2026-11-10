"""Postgres refuses `SELECT ... FOR UPDATE` on the nullable side of an outer join, while SQLite (used by most of the
suite) ignores row locks entirely. So every lock that is combined with select_related must lock only its own row."""

import re
from pathlib import Path

APPS = Path(__file__).resolve().parent.parent / "apps"
LOCK_THEN_JOIN = re.compile(r"select_for_update\(\)\s*\.select_related")
JOIN_THEN_LOCK = re.compile(r"\.select_related\([^)]*\)\s*\.select_for_update\(\)")


def test_locks_with_joins_lock_only_their_own_row():
    bad = []
    for path in APPS.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text()
        for m in [*LOCK_THEN_JOIN.finditer(text), *JOIN_THEN_LOCK.finditer(text)]:
            bad.append(f"{path.relative_to(APPS)}:{text.count(chr(10), 0, m.start()) + 1}")
    assert not bad, 'use select_for_update(of=("self",)) with select_related: ' + ", ".join(bad)


def test_ai_written_onboarding_goal_is_accepted_by_profile(auth):
    """The chat onboarding writes a one-line course goal (often ~100 chars); the profile must accept it (seen live)."""
    client, _ = auth
    goal = "Use Python and simple AI tools to build a basic billing and stock tracker for a small shop."
    res = client.patch("/api/users/profile/", {"goals": [goal], "onboarding_completed": True}, format="json")
    assert res.status_code == 200, res.data
    too_long = client.patch("/api/users/profile/", {"goals": ["x" * 201]}, format="json")
    assert too_long.status_code == 400 and too_long.data["goals"] == ["goal_too_long"]


def test_channel_layer_read_timeout_outlasts_the_blocking_receive(settings):
    """Real Redis: the channel layer blocks up to brpop_timeout per receive; a shorter socket read timeout kills every
    idle WebSocket (redis-py 8 defaults to 5 s, equal to channels_redis's wait)."""
    import importlib

    from channels_redis.core import RedisChannelLayer

    import config.settings as conf

    with __import__("unittest").mock.patch.dict(
        "os.environ", {"CHANNELS_REDIS_URL": "redis://localhost:6379/2"}
    ):
        conf = importlib.reload(conf)
        host = conf.CHANNEL_LAYERS["default"]["CONFIG"]["hosts"][0]
    importlib.reload(conf)
    assert host["address"] == "redis://localhost:6379/2"
    assert host["socket_timeout"] > RedisChannelLayer.brpop_timeout + 5


def test_readiness_pings_redis_channel_shards_without_receive(monkeypatch, client):
    """Repeated readiness checks must not use layer.receive (it binds to the first event loop and later checks hang)."""
    from unittest import mock

    pings = []

    class FakeRedis:
        async def ping(self):
            pings.append(1)
            return True

        async def aclose(self):
            pass

    layer = mock.Mock(hosts=[{"address": "redis://example:6379/2"}])
    layer.receive.side_effect = AssertionError("receive must not be used for Redis layers")
    monkeypatch.setattr("channels.layers.get_channel_layer", lambda *a, **k: layer)
    monkeypatch.setattr("redis.asyncio.from_url", lambda *a, **k: FakeRedis())
    from config import health

    monkeypatch.setitem(health.CHECKS, "db", lambda: None)
    monkeypatch.setitem(health.CHECKS, "cache", lambda: None)
    for _ in range(3):
        res = client.get("/api/health/ready/")
        assert res.status_code == 200, res.content
    assert len(pings) == 3


def test_onboarding_chat_tells_the_ai_the_learners_name(auth, monkeypatch):
    """Seen live: the AI called a learner 'Madurai' (her city). The prompt now carries her real name."""
    from apps.accounts.models import Profile
    from llm.prompts.paths import ONBOARD_SYSTEM

    client, _ = auth
    Profile.objects.filter(user__email="kavya@example.com").update(display_name="Priya\n{bad} Live")
    seen = {}
    real_format = str.format

    class Spy(str):
        def format(self, *a, **k):
            seen.update(k)
            return real_format(self, *a, **k)

    monkeypatch.setattr("llm.prompts.paths.ONBOARD_SYSTEM", Spy(ONBOARD_SYSTEM))
    client.post("/api/paths/onboarding-chat/", {"messages": []}, format="json")
    assert "Priya bad Live" in seen["name_rule"] and "never by a place" in seen["name_rule"]


def test_websocket_connections_do_sync_work_in_parallel():
    """Load test: slow sync work on one socket (AI grading inside database_sync_to_async) stalled every other socket in
    the worker, because thread-sensitive calls share one thread outside a ThreadSensitiveContext."""
    import asyncio
    import threading
    import time

    from channels.db import database_sync_to_async

    from config.asgi import application
    from config.asgi_threads import PerConnectionThreads

    assert isinstance(application.application_mapping["websocket"], PerConnectionThreads)
    threads = set()

    def slow():
        threads.add(threading.get_ident())
        time.sleep(0.4)

    async def app(scope, receive, send):
        await database_sync_to_async(slow)()

    wrapped = PerConnectionThreads(app)

    async def main():
        started = time.monotonic()
        await asyncio.gather(*(wrapped({"type": "websocket"}, None, None) for _ in range(4)))
        return time.monotonic() - started

    elapsed = asyncio.run(main())
    assert elapsed < 1.0, f"4 sockets took {elapsed:.2f}s: their sync work ran one after another"
    assert len(threads) == 4


def test_sync_ai_calls_hand_back_the_db_connection_first(monkeypatch):
    """Load test: pooled connections sat idle behind slow AI calls until PoolTimeout. complete_json_sync now releases
    the connection before calling the model, but never inside a transaction."""
    from pydantic import BaseModel

    from llm import structured

    calls = []
    monkeypatch.setattr("llm.dbconn.release_db", lambda: calls.append("released"))

    class Out(BaseModel):
        ok: bool = True

    async def fake_complete_json(*a, **k):
        calls.append("model")
        return Out()

    monkeypatch.setattr(structured, "complete_json", fake_complete_json)
    structured.complete_json_sync("grade", "sys", "user", Out)
    assert calls == ["released", "model"]


def test_release_db_skips_connections_inside_a_transaction(db):
    from django.db import connection, transaction

    from llm.dbconn import release_db

    with transaction.atomic():
        connection.ensure_connection()
        release_db()
        assert connection.connection is not None  # still usable inside the atomic block
