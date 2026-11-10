import base64

import pytest
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient

from apps.billing.models import Plan
from apps.live import consumers
from apps.live.consumers import _decode
from apps.live.models import LiveSession, LiveTurn
from apps.providers.models import ProviderConfig, UsageCounter
from config.asgi import application
from llm.base import ChatMessage, Image
from llm.prompts.live import SILENT
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _plans(db):
    """Transactional tests start from an empty DB, so re-run the plan seed migrations."""
    import importlib

    from django.apps import apps

    importlib.import_module("apps.billing.migrations.0002_seed_plans").seed(apps, None)
    importlib.import_module("apps.billing.migrations.0004_live_minutes_limit").add(apps, None)


JPEG = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 200).decode()


async def _connect(token):
    comm = WebsocketCommunicator(
        application, "/ws/live/", headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")]
    )
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": token})
    assert (await comm.receive_json_from())["type"] == "ready"
    return comm


async def _until(comm, pred, limit=200):
    seen = []
    for _ in range(limit):
        ev = await comm.receive_json_from(timeout=5)
        seen.append(ev)
        if pred(ev):
            return seen
    raise AssertionError(seen)


def _turn_done(ev):
    return ev["type"] == "mascot" and ev["state"] == "idle"


def test_decode_checks_real_image_bytes():
    assert _decode(JPEG).media_type == "image/jpeg"
    fake = "data:image/jpeg;base64," + base64.b64encode(b"<script>alert(1)</script>").decode()
    assert _decode(fake) is None
    assert _decode("http://evil/x.jpg") is None
    huge = "data:image/jpeg;base64," + "A" * 900_000
    assert _decode(huge) is None


def test_providers_send_images_as_blocks():
    from llm.providers.anthropic_provider import _content as anthropic_content
    from llm.providers.openai_provider import _content as openai_content

    m = ChatMessage("user", "is this right?", images=[Image("image/jpeg", "QUJD")])
    a = anthropic_content(m)
    assert (
        a[0]["type"] == "image"
        and a[0]["source"]["data"] == "QUJD"
        and a[-1] == {"type": "text", "text": "is this right?"}
    )
    o = openai_content(m)
    assert o[0]["image_url"]["url"] == "data:image/jpeg;base64,QUJD"
    assert anthropic_content(ChatMessage("user", "plain")) == "plain"


async def test_live_class_flow(auth, monkeypatch):
    monkeypatch.setattr(consumers, "MIN_FRAME_GAP", 0)
    _, data = auth
    comm = await _connect(data["access"])
    await comm.send_json_to({"type": "start", "mode": "camera", "topic": "Adding fractions"})
    started = await comm.receive_json_from(timeout=5)
    assert started["type"] == "started" and started["minutes_left"] == 10
    greet = await _until(comm, _turn_done)
    assert any(e["type"] == "start" and e["proactive"] for e in greet)

    await comm.send_json_to({"type": "frame", "image": JPEG, "reason": "snapshot"})
    assert (await comm.receive_json_from(timeout=5)) == {"type": "frame_ok", "accepted": True}
    await comm.send_json_to({"type": "say", "text": "Is my answer 3/7 right?"})
    reply = await _until(comm, _turn_done)
    start = next(e for e in reply if e["type"] == "start")
    assert start["saw"] is True and start["proactive"] is False

    await comm.send_json_to({"type": "say", "text": "What should I do next?"})
    await _until(comm, _turn_done)
    await comm.send_json_to({"type": "end"})
    summ = await _until(comm, lambda e: e["type"] == "summary")
    assert summ[-1]["summary"]["title"] == "Fractions practice"
    await comm.disconnect()

    s = await LiveSession.objects.aget(pk=started["session_id"])
    assert s.ended_at and s.frames == 1 and s.topic == "Adding fractions"
    texts = [t async for t in LiveTurn.objects.filter(session=s).values_list("text", flat=True)]
    assert "Is my answer 3/7 right?" in texts
    assert not any("base64" in t or "/9j/" in t for t in texts)  # snapshots are never stored


async def test_glance_can_stay_silent(auth, monkeypatch):
    monkeypatch.setattr(consumers, "MIN_FRAME_GAP", 0)
    monkeypatch.setattr(consumers, "GLANCE_GAP", 0)
    orig = fake_provider.FakeProvider._reply
    monkeypatch.setattr(
        fake_provider.FakeProvider,
        "_reply",
        lambda self, req: (
            SILENT if "No words from the learner" in req.messages[-1].content else orig(self, req)
        ),
    )
    _, data = auth
    comm = await _connect(data["access"])
    await comm.send_json_to({"type": "start", "mode": "camera"})
    await _until(comm, _turn_done)
    await comm.send_json_to({"type": "frame", "image": JPEG, "reason": "change"})
    evs = await _until(comm, lambda e: e["type"] == "silent")
    assert not any(e["type"] == "delta" for e in evs)
    await comm.disconnect()


async def test_frames_rate_limited_and_budgeted(auth, monkeypatch):
    await ProviderConfig.objects.acreate(
        capability="vision",
        provider="anthropic",
        model="claude-sonnet-5-5",
        limits={"vision_frames_per_day": 1},
    )
    _, data = auth
    comm = await _connect(data["access"])
    await comm.send_json_to({"type": "start", "mode": "screen"})
    await _until(comm, _turn_done)
    await comm.send_json_to({"type": "frame", "image": JPEG})
    assert (await comm.receive_json_from(timeout=5))["accepted"] is True
    await comm.send_json_to({"type": "frame", "image": JPEG})
    assert (await comm.receive_json_from(timeout=5)) == {
        "type": "frame_ok",
        "accepted": False,
        "reason": "too_fast",
    }
    monkeypatch.setattr(consumers, "MIN_FRAME_GAP", 0)
    await comm.send_json_to({"type": "frame", "image": JPEG})
    assert (await comm.receive_json_from(timeout=5))["code"] == "vision_budget_exceeded"
    await comm.disconnect()


async def test_start_blocked_when_daily_live_minutes_used(auth):
    from django.utils import timezone

    from apps.accounts.models import User

    _, data = auth
    u = await User.objects.aget(email="kavya@example.com")
    await UsageCounter.objects.acreate(
        user=u, day=timezone.localdate(), metric="live_seconds", amount=10 * 60
    )
    comm = await _connect(data["access"])
    await comm.send_json_to({"type": "start", "mode": "camera"})
    ev = await comm.receive_json_from(timeout=5)
    assert ev["code"] == "plan_limit" and ev["limit"] == "live_minutes_per_day"
    await comm.disconnect()


def test_free_and_plus_plans_have_live_minutes():
    assert Plan.objects.get(code="free").limits["live_minutes_per_day"] == 10
    assert Plan.objects.get(code="plus_year").limits["live_minutes_per_day"] == 60


def test_sessions_api_is_private(auth):
    c, _ = auth
    from apps.accounts.models import User

    other = User.objects.create_user("o@x.in", "Other#2026pass")
    mine = LiveSession.objects.create(user=User.objects.get(email="kavya@example.com"), topic="mine")
    theirs = LiveSession.objects.create(user=other, topic="theirs")
    assert [s["topic"] for s in c.get("/api/live/sessions/").data] == ["mine"]
    assert c.get(f"/api/live/sessions/{theirs.id}/").status_code == 404
    assert c.get(f"/api/live/sessions/{mine.id}/").data["turns"] == []
    assert APIClient().get("/api/live/sessions/").status_code == 401
