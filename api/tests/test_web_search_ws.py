"""Live web search and the input guard on the real sockets (fake provider: time-sensitive questions "search")."""

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from apps.mentor.models import Message
from config.asgi import application
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db(transaction=True)
HEADERS = [(b"host", b"localhost"), (b"origin", b"http://localhost:5173")]


@pytest.fixture
def requests_seen(monkeypatch):
    seen = []
    orig = fake_provider.FakeProvider.stream

    def stream(self, req):
        seen.append(req)
        return orig(self, req)

    monkeypatch.setattr(fake_provider.FakeProvider, "stream", stream)
    return seen


async def _socket(path, token):
    comm = WebsocketCommunicator(application, path, headers=HEADERS)
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": token})
    assert (await comm.receive_json_from())["type"] == "ready"
    return comm


async def _ask(comm, payload):
    await comm.send_json_to({"type": "message", **payload})
    events = []
    while True:
        ev = await comm.receive_json_from(timeout=5)
        events.append(ev)
        if ev["type"] == "mascot" and ev["state"] == "idle":
            return events


async def test_current_question_searches_and_returns_sources(auth, requests_seen):
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    events = await _ask(comm, {"text": "What is the gold price in Chennai today?", "via": "voice"})
    await comm.disconnect()
    types = [e["type"] for e in events]
    assert types.index("status") < types.index("delta")  # "searching" before the first word
    assert next(e for e in events if e["type"] == "status")["state"] == "searching"
    done = next(e for e in events if e["type"] == "done")
    assert {"kind": "web", "title": "Example news (demo search)", "url": "https://example.org/news"} in done[
        "citations"
    ]
    req = requests_seen[0]
    assert req.web_search and "<web_search_rules>" in req.system and "You can search the web" in req.system
    assert req.system.endswith("</director_note>")  # the spoken note stays last
    msg = await Message.objects.aget(id=done["message_id"])
    assert msg.citations == done["citations"]


async def test_concept_question_offers_search_but_does_not_search(auth, requests_seen):
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    events = await _ask(comm, {"text": "What is a neural network?"})
    await comm.disconnect()
    assert "status" not in [e["type"] for e in events]
    assert next(e for e in events if e["type"] == "done")["citations"] == []


async def test_search_off_by_setting(auth, requests_seen, settings):
    settings.MENTOR_WEB_SEARCH = False
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    events = await _ask(comm, {"text": "latest news on ISRO?"})
    await comm.disconnect()
    assert "status" not in [e["type"] for e in events]
    assert not requests_seen[0].web_search and "cannot search the web" in requests_seen[0].system


async def test_daily_search_cap(auth, requests_seen, settings):
    settings.MENTOR_WEB_SEARCH_PER_DAY = 1
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    first = await _ask(comm, {"text": "cricket score today?"})
    conv = first[0]["conversation_id"]
    second = await _ask(comm, {"text": "and the latest news?", "conversation_id": conv})
    await comm.disconnect()
    assert "status" in [e["type"] for e in first] and "status" not in [e["type"] for e in second]
    assert [r.web_search for r in requests_seen] == [True, False]


async def test_documents_chat_searches_only_when_asked(auth, requests_seen):
    from tests.test_docs import NOTES, upload

    client, data = auth
    doc_id = (await sync_to_async(upload)(client, "notes.txt", NOTES.encode())).data["id"]
    comm = await _socket("/ws/assistant/", data["access"])
    a = await _ask(comm, {"text": "What is machine learning?", "document_id": doc_id})
    conv = a[0]["conversation_id"]
    await _ask(comm, {"text": "Search the web for the latest on this", "conversation_id": conv})
    await comm.disconnect()
    assert [r.web_search for r in requests_seen] == [False, True]


async def test_secrets_are_masked_before_the_model_and_the_database(auth, requests_seen):
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    events = await _ask(comm, {"text": "my otp is 482913, keep it for me"})
    await comm.disconnect()
    assert "482913" not in requests_seen[0].messages[-1].content
    assert "[hidden code]" in requests_seen[0].messages[-1].content
    conv = events[0]["conversation_id"]
    stored = [m async for m in Message.objects.filter(conversation_id=conv).values_list("content", flat=True)]
    assert not any("482913" in m for m in stored)


async def test_crisis_adds_the_one_turn_note(auth, requests_seen):
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    events = await _ask(comm, {"text": "I want to die, nothing matters"})
    await _ask(comm, {"text": "what is recursion?", "conversation_id": events[0]["conversation_id"]})
    await comm.disconnect()
    assert "may mean they are in distress" in requests_seen[0].system
    assert "may mean they are in distress" not in requests_seen[1].system


async def test_model_written_images_never_reach_the_learner(auth, monkeypatch):
    from llm.base import StreamEvent

    async def stream(self, req):
        for piece in ["Look ![x](https://ev", "il.example/?q=otp) here and [site](https://x.example)."]:
            yield StreamEvent(delta=piece)
        yield StreamEvent(done=True, stop_reason="end_turn", model="fake")

    monkeypatch.setattr(fake_provider.FakeProvider, "stream", stream)
    _, data = auth
    comm = await _socket("/ws/assistant/", data["access"])
    events = await _ask(comm, {"text": "hello"})
    await comm.disconnect()
    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert text == "Look  here and site."
    msg = await Message.objects.aget(id=next(e for e in events if e["type"] == "done")["message_id"])
    assert msg.content == text


# ── Live Class ──────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def _plans(db):
    import importlib

    from django.apps import apps

    importlib.import_module("apps.billing.migrations.0002_seed_plans").seed(apps, None)
    importlib.import_module("apps.billing.migrations.0004_live_minutes_limit").add(apps, None)


async def _live_until_idle(comm):
    events = []
    while True:
        ev = await comm.receive_json_from(timeout=5)
        events.append(ev)
        if ev["type"] == "mascot" and ev["state"] == "idle":
            return events


async def test_live_class_searches_for_learner_questions_not_glances(auth, requests_seen, _plans):
    _, data = auth
    comm = await _socket("/ws/live/", data["access"])
    await comm.send_json_to({"type": "start", "mode": "none", "topic": "Current affairs"})
    assert (await comm.receive_json_from(timeout=5))["type"] == "started"
    await _live_until_idle(comm)  # the greeting
    await comm.send_json_to({"type": "say", "text": "What is the latest news on Chandrayaan? my pin is 4521"})
    events = await _live_until_idle(comm)
    await comm.disconnect()
    types = [e["type"] for e in events]
    assert "status" in types and types.index("status") < types.index("delta")
    done = next(e for e in events if e["type"] == "done")
    assert done["sources"] == [{"title": "Example news (demo search)", "url": "https://example.org/news"}]
    asked = requests_seen[-1]
    assert asked.web_search and "4521" not in asked.messages[-1].content
    assert "<learner_topic>" in asked.system


# ── Role-play: searches, in character ───────────────────────────────────────────────────────────────────────


async def test_roleplay_searches_in_character_and_masks_secrets(auth, requests_seen):
    from apps.roleplay.models import RolePlayTurn
    from tests.test_roleplay import library_id

    client, data = auth
    sid = await sync_to_async(library_id)(client, "Ask your teacher for help")
    s = (
        await sync_to_async(client.post)("/api/roleplay/sessions/", {"scenario_id": sid}, format="json")
    ).data
    comm = await _socket("/ws/roleplay/", data["access"])
    await comm.send_json_to(
        {"type": "message", "session_id": s["id"], "text": "What's today's news? my password is Mango#77"}
    )
    events = []
    while not events or events[-1]["type"] not in ("done", "error"):
        events.append(await comm.receive_json_from(timeout=5))
    await comm.disconnect()
    types = [e["type"] for e in events]
    assert "status" in types and types.index("status") < types.index("delta")
    done = events[-1]
    assert done["type"] == "done"
    assert done["sources"] == [{"title": "Example news (demo search)", "url": "https://example.org/news"}]
    req = requests_seen[-1]
    assert req.web_search and "Guardrails" in req.system
    assert "Stay in character and in the scene" in req.system  # the role-play search rules
    texts = [t async for t in RolePlayTurn.objects.filter(session_id=s["id"]).values_list("text", flat=True)]
    assert not any("Mango#77" in t for t in texts)


async def test_roleplay_respects_the_search_switch(auth, requests_seen, settings):
    from tests.test_roleplay import library_id

    settings.MENTOR_WEB_SEARCH = False
    client, data = auth
    sid = await sync_to_async(library_id)(client, "Ask your teacher for help")
    s = (
        await sync_to_async(client.post)("/api/roleplay/sessions/", {"scenario_id": sid}, format="json")
    ).data
    comm = await _socket("/ws/roleplay/", data["access"])
    await comm.send_json_to({"type": "message", "session_id": s["id"], "text": "What's today's news?"})
    events = []
    while not events or events[-1]["type"] not in ("done", "error"):
        events.append(await comm.receive_json_from(timeout=5))
    await comm.disconnect()
    assert "status" not in [e["type"] for e in events] and events[-1]["sources"] == []
    assert not requests_seen[-1].web_search and "You cannot search the web" in requests_seen[-1].system
