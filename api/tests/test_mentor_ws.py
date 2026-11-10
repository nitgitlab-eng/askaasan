import pytest
from channels.testing import WebsocketCommunicator
from rest_framework import serializers

from apps.accounts.preferences import default_preferences, upgrade
from apps.accounts.serializers import validate_preferences_patch
from apps.mentor.models import Message
from config.asgi import application
from llm.prompts.tutor import SPOKEN_TURN_NOTE
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db(transaction=True)


async def _connect():
    comm = WebsocketCommunicator(
        application,
        "/ws/assistant/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    connected, _ = await comm.connect()
    assert connected
    return comm


async def test_rejects_bad_token():
    comm = await _connect()
    await comm.send_json_to({"type": "auth", "token": "nope"})
    assert (await comm.receive_json_from())["code"] == "unauthorized"
    await comm.disconnect()


async def test_streams_reply_with_mascot_cues(auth):
    _, data = auth
    comm = await _connect()
    await comm.send_json_to({"type": "auth", "token": data["access"]})
    assert (await comm.receive_json_from())["type"] == "ready"

    await comm.send_json_to({"type": "message", "text": "Machine learning என்றால் என்ன?"})
    events = []
    while True:
        ev = await comm.receive_json_from(timeout=5)
        events.append(ev)
        if ev["type"] == "mascot" and ev["state"] == "idle":
            break
    types = [e["type"] for e in events]
    assert types[0] == "start" and "delta" in types and "done" in types
    states = [e["state"] for e in events if e["type"] == "mascot"]
    assert states == ["thinking", "talking", "idle"]
    text = "".join(e["text"] for e in events if e["type"] == "delta")
    assert "Demo mode" in text

    conv_id = events[0]["conversation_id"]
    assert await Message.objects.filter(conversation_id=conv_id).acount() == 2
    await comm.disconnect()


async def _turn(comm, payload):
    await comm.send_json_to(payload)
    while True:
        ev = await comm.receive_json_from(timeout=5)
        if ev["type"] == "mascot" and ev["state"] == "idle":
            return


@pytest.mark.parametrize("via, noted", [("voice", True), (None, False), ("typed", False)])
async def test_spoken_question_gets_a_spoken_answer_note(auth, monkeypatch, via, noted):
    seen = []
    orig = fake_provider.FakeProvider.stream

    def stream(self, req):
        seen.append(req)
        return orig(self, req)

    monkeypatch.setattr(fake_provider.FakeProvider, "stream", stream)
    _, data = auth
    comm = await _connect()
    await comm.send_json_to({"type": "auth", "token": data["access"]})
    assert (await comm.receive_json_from())["type"] == "ready"
    msg = {"type": "message", "text": "What is a neural network?"}
    if via:
        msg["via"] = via
    await _turn(comm, msg)
    await comm.disconnect()
    assert len(seen) == 1
    system = seen[0].system
    assert (SPOKEN_TURN_NOTE in system) is noted
    assert ("<director_note>" in system) is noted
    if noted:
        assert system.endswith("</director_note>")  # appended last: the cached tutor prefix stays byte-stable
        assert "120 words" in system and "one short question" in system


def test_preferences_accept_the_system_theme():
    """Theme "system" (Follow my device) is stored as-is; light stays the default and junk is still rejected."""
    assert default_preferences()["appearance"]["theme"] == "light"
    out = validate_preferences_patch({}, {"appearance": {"theme": "system"}})
    assert out["appearance"]["theme"] == "system"
    assert upgrade({"version": 2, "appearance": {"theme": "system"}})["appearance"]["theme"] == "system"
    for bad in ("auto", "device", "System", "", None):
        with pytest.raises(serializers.ValidationError):
            validate_preferences_patch({}, {"appearance": {"theme": bad}})


def test_preferences_accept_the_mentor_voice_mode():
    assert default_preferences()["voice"]["mentor_mode"] == "tap"
    assert upgrade({"version": 2, "voice": {"workshop_mode": "handsfree"}})["voice"] == {
        "workshop_mode": "handsfree",
        "mentor_mode": "tap",
        "mentor_read_aloud": True,
        "mentor_lang": "",
    }
    out = validate_preferences_patch({}, {"voice": {"mentor_mode": "handsfree", "mentor_read_aloud": False}})
    assert out["voice"]["mentor_mode"] == "handsfree" and out["voice"]["mentor_read_aloud"] is False
    assert validate_preferences_patch({}, {"voice": {"mentor_lang": "ta"}})["voice"]["mentor_lang"] == "ta"
    for bad in (
        {"mentor_mode": "always"},
        {"mentor_mode": ""},
        {"mentor_read_aloud": "loud"},
        {"mentor_lang": "fr"},
    ):
        with pytest.raises(serializers.ValidationError):
            validate_preferences_patch({}, {"voice": bad})


async def test_a_socket_that_never_authenticates_is_closed(monkeypatch):
    from apps.mentor import consumers

    monkeypatch.setattr(consumers, "AUTH_TIMEOUT", 0.05)
    comm = await _connect()
    assert (await comm.receive_json_from(timeout=2))["code"] == "unauthorized"
    assert (await comm.receive_output(timeout=2))["type"] == "websocket.close"


async def test_an_authenticated_socket_stays_open_past_the_auth_timeout(auth, monkeypatch):
    import asyncio

    from apps.mentor import consumers

    monkeypatch.setattr(consumers, "AUTH_TIMEOUT", 0.05)
    _, data = auth
    comm = await _connect()
    await comm.send_json_to({"type": "auth", "token": data["access"]})
    assert (await comm.receive_json_from())["type"] == "ready"
    await asyncio.sleep(0.2)
    assert await comm.receive_nothing(timeout=0.1)
    await comm.disconnect()
