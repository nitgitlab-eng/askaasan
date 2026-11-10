"""API bugs found by the Playwright e2e suite."""

import pytest
from channels.testing import WebsocketCommunicator

from config.asgi import application


async def _mentor(token):
    comm = WebsocketCommunicator(
        application,
        "/ws/assistant/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": token})
    assert (await comm.receive_json_from())["type"] == "ready"
    return comm


@pytest.mark.django_db(transaction=True)
async def test_mentor_reports_unexpected_errors_instead_of_hanging(auth, monkeypatch):
    """An unexpected exception in the reply task used to send neither `error` nor `done`: the chat waited forever."""
    from apps.mentor.consumers import AssistantConsumer

    async def boom(self, content):
        raise RuntimeError("database went away")

    monkeypatch.setattr(AssistantConsumer, "_reply", boom)
    _, data = auth
    comm = await _mentor(data["access"])
    await comm.send_json_to({"type": "message", "text": "hello"})
    ev = await comm.receive_json_from(timeout=5)
    assert ev == {"type": "error", "code": "server_error", "retryable": True}
    await comm.disconnect()


def test_course_generation_failure_after_the_ai_call_marks_the_course_failed(auth, monkeypatch):
    """A DB error while saving the outline killed the job and left the course 'generating' forever."""
    from apps.learning import services
    from apps.learning.models import Curriculum, Section

    client, _ = auth
    res = client.post(
        "/api/learn/curriculums/",
        {"goal": "Learn Python for shop billing", "level": "beginner"},
        format="json",
    )
    cid = res.data["id"]
    Curriculum.objects.filter(id=cid).update(status=Curriculum.Status.GENERATING)

    def broken_create(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(Section.objects, "create", broken_create)
    services.generate_outline(cid)
    cur = Curriculum.objects.get(id=cid)
    assert cur.status == Curriculum.Status.FAILED and cur.error == "internal_error"


def test_sqlite_waits_for_the_write_lock_instead_of_failing():
    from config.settings import database_config

    db = database_config("sqlite:///tmp/x.sqlite3")
    assert db["OPTIONS"] == {"transaction_mode": "IMMEDIATE", "timeout": 20}
    assert "transaction_mode" not in database_config("postgres://u:p@h:5432/d").get("OPTIONS", {})


@pytest.mark.django_db(transaction=True)
async def test_mentor_retries_once_on_a_retryable_ai_error_before_any_words(auth, monkeypatch):
    """A new user's first question can hit a brief rate limit while their first course is built on the same AI key:
    wait a moment and try once more instead of showing an error straight away."""
    from apps.mentor import consumers
    from llm.base import LLMError
    from llm.providers.fake_provider import FakeProvider

    monkeypatch.setattr(consumers, "RETRY_DELAY", 0)
    real = FakeProvider.stream
    calls = []

    async def flaky(self, req):
        calls.append(1)
        if len(calls) == 1:
            raise LLMError("rate_limited", "busy", retryable=True)
        async for ev in real(self, req):
            yield ev

    monkeypatch.setattr(FakeProvider, "stream", flaky)
    _, data = auth
    comm = await _mentor(data["access"])
    await comm.send_json_to({"type": "message", "text": "What is AI?"})
    events = []
    while True:
        ev = await comm.receive_json_from(timeout=5)
        events.append(ev)
        if ev["type"] in ("done", "error"):
            break
    assert events[-1]["type"] == "done" and len(calls) == 2
    assert any(e["type"] == "delta" for e in events)
    await comm.disconnect()
