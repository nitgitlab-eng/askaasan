"""AI workshops over the socket (ws/workshop/<id>/), following the test_mentor_ws pattern with the fake provider."""

from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator

from apps.accounts.models import User
from apps.workshops import consumers, services
from apps.workshops.content import seed
from apps.workshops.models import (
    WorkshopEnrollment,
    WorkshopEvent,
    WorkshopRun,
    WorkshopSession,
    WorkshopTurn,
)
from config.asgi import application
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _fast(monkeypatch, db):
    seed()  # transactional tests start from an empty DB
    orig = fake_provider.FakeProvider.__init__
    monkeypatch.setattr(fake_provider.FakeProvider, "__init__", lambda self, delay=0.0: orig(self, 0.0))


def _make(email="kavya@example.com", slug="quick-check", started=True, proctoring=""):
    from apps.workshops.models import Workshop

    user = User.objects.get(email=email)
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug=slug),
        audience="test",
        starts_at=services.now(),
        status="live",
        created_by=user,
        proctoring=proctoring,
    )
    e = WorkshopEnrollment.objects.create(run=run, user=user)
    s = WorkshopSession.objects.create(enrollment=e, user=user, run=run)
    if started:
        s.prereqs_done = {p["key"]: "x" for p in run.workshop.prerequisites}
        s.save()
        services.start(s)
    return s.id


make = sync_to_async(_make)


async def _connect(sid, token):
    comm = WebsocketCommunicator(
        application,
        f"/ws/workshop/{sid}/",
        headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")],
    )
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": token})
    return comm


async def _until(comm, pred, limit=400):
    seen = []
    for _ in range(limit):
        ev = await comm.receive_json_from(timeout=5)
        seen.append(ev)
        if pred(ev):
            return seen
    raise AssertionError(seen)


def _done(ev):
    return ev["type"] == "done"


def _suggest(ev):
    """The end of a completed host turn: done → (progress) → suggest."""
    return ev["type"] == "suggest"


@sync_to_async
def _state(sid):
    s = services.load(sid)
    return s, services.state(s)


async def test_socket_is_owner_only(auth):
    from rest_framework.test import APIClient

    _, data = auth
    sid = await make()
    c = APIClient()
    other = await sync_to_async(c.post)(
        "/api/users/register/", {"email": "arun@example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    comm = await _connect(sid, other.data["access"])
    assert (await comm.receive_json_from())["code"] == "not_found"
    assert (await comm.receive_output())["type"] == "websocket.close"
    bad = await _connect(sid, "nope")
    assert (await bad.receive_json_from())["code"] == "unauthorized"
    await comm.disconnect()
    await bad.disconnect()


async def test_concept_flow_and_resume_after_disconnect(auth):
    _, data = auth
    sid = await make()
    comm = await _connect(sid, data["access"])
    ready = await comm.receive_json_from()
    assert ready["type"] == "ready" and ready["session"]["status"] == "active" and ready["turns"] == []
    assert (await comm.receive_json_from())["type"] == "pace"
    # The current concept is explained on first connect, streamed.
    seen = await _until(comm, _done)
    assert seen[0]["type"] == "start" and any(e["type"] == "delta" for e in seen)
    prog = await comm.receive_json_from()
    assert prog["type"] == "progress" and prog["session"]["stages"][0]["concepts"][0]["explained"]
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": ["not_sure", "example", "tamil"]}
    # The learner answers the check: assessed, marked done, no auto-advance.
    await comm.send_json_to(
        {"type": "say", "text": "It learns from many examples, like my aunt picking mangoes."}
    )
    prog = await comm.receive_json_from()
    assert prog["type"] == "progress" and prog["session"]["stages"][0]["concepts"][0]["done"]
    assert prog["session"]["stages"][0]["cursor"] == 0 and prog["session"]["stages"][0]["ready_to_move"]
    await _until(comm, _done)
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": ["yes_next", "not_yet"]}
    await comm.send_json_to({"type": "next"})
    prog = await comm.receive_json_from()
    assert prog["type"] == "progress" and prog["session"]["stages"][0]["cursor"] == 1
    await _until(comm, _done)
    await _until(comm, lambda e: e["type"] == "progress")
    await comm.disconnect()

    s, st = await _state(sid)
    assert s.status == "active" and s.ended_at is None and st["cursor"] == 1  # a disconnect never ends it
    turns = await WorkshopTurn.objects.filter(session_id=sid).acount()
    comm = await _connect(sid, data["access"])
    ready = await comm.receive_json_from()
    assert ready["session"]["stages"][0]["cursor"] == 1 and ready["session"]["stage_index"] == 0
    assert ready["turns"] and ready["turns"][-1]["role"] == "assistant"
    assert set(ready["turns"][0]) >= {"role", "text"}
    assert (await comm.receive_json_from())["type"] == "pace"
    assert await comm.receive_nothing(timeout=0.3)  # already explained: no repeat on resume
    assert await WorkshopTurn.objects.filter(session_id=sid).acount() == turns
    await comm.send_json_to({"type": "control", "action": "again"})
    seen = await _until(comm, _suggest)
    assert seen[0]["type"] == "start"
    await comm.send_json_to({"type": "control", "action": "nope"})
    assert (await comm.receive_json_from())["code"] == "bad_control"
    await comm.send_json_to({"type": "say", "text": "x" * 2001})
    assert (await comm.receive_json_from())["code"] == "too_long"
    await comm.disconnect()


async def test_next_mid_turn_interrupts_and_needs_explanation(auth):
    _, data = auth
    sid = await make()
    comm = await _connect(sid, data["access"])
    await comm.receive_json_from()  # ready
    await comm.receive_json_from()  # pace
    await comm.send_json_to({"type": "next"})  # the opening explanation is still streaming
    seen = await _until(comm, lambda e: e["type"] == "error")
    assert not any(e.get("code") == "busy" for e in seen)
    assert {"type": "done", "stop_reason": "cancelled"} in seen
    assert seen[-1]["code"] == "not_explained"  # the interrupted explanation doesn't count
    await comm.disconnect()
    await sync_to_async(WorkshopSession.objects.filter(pk=sid).update)(stage_state={})
    comm = await _connect(sid, data["access"])
    await _until(comm, _done)
    await comm.disconnect()


async def test_diy_step_done_over_socket(auth):
    _, data = auth
    sid = await make()
    await sync_to_async(WorkshopSession.objects.filter(pk=sid).update)(stage_index=1)
    comm = await _connect(sid, data["access"])
    await _until(comm, _done)  # step explained
    await _until(comm, lambda e: e["type"] == "progress")
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": ["done", "stuck"]}
    await comm.send_json_to({"type": "step_done", "step": 0})
    prog = await comm.receive_json_from()
    assert prog["type"] == "progress" and prog["session"]["stages"][1]["steps"][0]["done"]
    assert prog["session"]["stage_index"] == 1
    await _until(comm, _done)  # "what did you see?"
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": ["yes_next", "not_yet"]}
    assert await WorkshopEvent.objects.filter(session_id=sid, type="diy_step_done").aexists()
    await comm.send_json_to({"type": "next"})
    prog = await comm.receive_json_from()
    assert prog["session"]["stage_index"] == 2 and prog["session"]["stage_kind"] == "assessment"
    await _until(comm, _done)
    await comm.disconnect()


async def test_attention_events_follow_proctoring(auth):
    _, data = auth
    off = await make()
    comm = await _connect(off, data["access"])
    await _until(comm, _suggest)
    await comm.send_json_to({"type": "attention", "kind": "hidden"})
    await comm.send_json_to({"type": "attention", "kind": "visible"})
    assert await comm.receive_nothing(timeout=0.3)  # rejected silently
    assert not await WorkshopEvent.objects.filter(session_id=off, type__startswith="tab_").aexists()
    await comm.disconnect()

    on = await make(proctoring="activity")
    comm = await _connect(on, data["access"])
    await _until(comm, _suggest)
    await comm.send_json_to({"type": "attention", "kind": "blur"})
    await comm.send_json_to({"type": "attention", "kind": "focus"})
    await comm.receive_nothing(timeout=0.3)
    kinds = [e async for e in WorkshopEvent.objects.filter(session_id=on).values_list("type", flat=True)]
    assert "blur" in kinds and "focus" in kinds
    # DIY stage: paused.
    await sync_to_async(WorkshopSession.objects.filter(pk=on).update)(stage_index=1)
    await comm.send_json_to({"type": "attention", "kind": "hidden"})
    await comm.receive_nothing(timeout=0.3)
    assert not await WorkshopEvent.objects.filter(session_id=on, type="tab_hidden").aexists()
    await comm.disconnect()


async def test_grace_and_overtime_pace_with_frozen_clock(auth, monkeypatch):
    _, data = auth
    sid = await make()
    s = await sync_to_async(services.load)(sid)
    clock = {"t": s.started_at + timedelta(minutes=11)}  # past the 10-minute plan
    monkeypatch.setattr(services, "now", lambda: clock["t"])
    monkeypatch.setattr(consumers, "CLOCK_EVERY", 0.05)
    comm = await _connect(sid, data["access"])
    ready = await comm.receive_json_from()
    assert ready["session"]["pace"]["status"] == "in_grace"
    pace = await comm.receive_json_from()
    assert pace == {
        "type": "pace",
        "status": "in_grace",
        "minutes_left": 9,
        "message": "Your timeline is over — you're in a grace period.",
    }
    await _until(comm, _done)  # the opening explanation
    # The host announces the grace period once.
    seen = await _until(comm, lambda e: e["type"] == "start")
    await _until(comm, _done)
    assert (await sync_to_async(services.load)(sid)).grace_announced
    clock["t"] = s.started_at + timedelta(minutes=25)
    seen = await _until(comm, lambda e: e["type"] == "pace" and e["status"] == "overtime")
    seen = [e for e in (await _until(comm, lambda e: e["type"] == "pace")) if e["type"] == "start"]
    assert not seen  # no second announcement
    s = await sync_to_async(services.load)(sid)
    assert (
        s.status == "overtime" and s.stage_index == 0 and s.ended_at is None
    )  # never auto-advanced or ended
    await comm.send_json_to({"type": "say", "text": "Patterns from examples!"})
    await _until(comm, _done)  # the learner simply carries on
    await comm.disconnect()


async def test_budget_pause(auth, settings):
    _, data = auth
    sid = await make()
    settings.WORKSHOP_SESSION_AI_UNITS = 5
    await sync_to_async(WorkshopSession.objects.filter(pk=sid).update)(ai_units=5)
    comm = await _connect(sid, data["access"])
    ready = await comm.receive_json_from()
    assert ready["session"]["paused"] == "budget"
    await comm.receive_json_from()  # pace
    assert await comm.receive_json_from() == {"type": "paused", "reason": "budget"}
    # Next still works while paused, so the learner is never trapped.
    await comm.send_json_to({"type": "next"})
    prog = await comm.receive_json_from()
    assert prog["type"] == "progress" and prog["session"]["stages"][0]["cursor"] == 1
    assert (await comm.receive_json_from()) == {"type": "paused", "reason": "budget"}
    await comm.disconnect()


async def test_prereq_screen_chat_and_raise_hand(auth):
    _, data = auth
    sid = await make(started=False)
    comm = await _connect(sid, data["access"])
    ready = await comm.receive_json_from()
    assert ready["session"]["status"] == "prereq" and ready["session"]["pace"] is None
    await comm.send_json_to({"type": "next"})
    assert (await comm.receive_json_from())["code"] == "not_started"
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": []}  # refusals re-send the chips
    await comm.send_json_to({"type": "say", "text": "How do I sign in to Gemini?"})
    seen = await _until(comm, _done)
    assert seen[0]["type"] == "start"
    await comm.send_json_to({"type": "raise_hand"})
    await _until(comm, _done)
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": []}  # not started: no chips
    assert await WorkshopEvent.objects.filter(session_id=sid, type="raise_hand").aexists()
    await comm.send_json_to({"type": "auth", "token": data["access"]})  # re-auth sends the full state
    again = await comm.receive_json_from()
    assert again["type"] == "ready" and again["session"]["id"] == sid
    await comm.disconnect()


async def test_socket_opened_on_prereq_screen_starts_teaching_after_start_and_reauth(auth):
    """The page connects on the prerequisites screen, before Start. After Start, the client re-authenticates and the
    host must begin the first concept; a later token renewal mid-item must stay silent."""
    _, data = auth
    sid = await make(started=False)
    comm = await _connect(sid, data["access"])
    ready = await comm.receive_json_from()
    assert ready["type"] == "ready" and ready["session"]["status"] == "prereq"
    assert await comm.receive_nothing(timeout=0.3)  # nothing to teach before Start

    @sync_to_async
    def start():
        s = WorkshopSession.objects.get(pk=sid)
        s.prereqs_done = {p["key"]: "x" for p in s.run.workshop.prerequisites}
        s.save()
        services.start(s)

    await start()
    await comm.send_json_to(
        {"type": "auth", "token": data["access"]}
    )  # what the page sends right after Start
    seen = await _until(comm, _done)
    assert seen[0]["type"] == "ready" and seen[0]["session"]["status"] == "active"
    assert any(e["type"] == "delta" for e in seen)
    prog = await comm.receive_json_from()
    assert prog["type"] == "progress" and prog["session"]["stages"][0]["concepts"][0]["explained"]
    assert (await comm.receive_json_from())["type"] == "suggest"

    await comm.send_json_to({"type": "auth", "token": data["access"]})  # periodic renewal mid-item
    assert (await comm.receive_json_from())["type"] == "ready"
    assert await comm.receive_nothing(timeout=0.3)  # the explained item is not repeated
    await comm.disconnect()


async def test_learner_questions_search_but_never_for_the_answers(auth, monkeypatch):
    seen = []
    orig = fake_provider.FakeProvider.stream

    def stream(self, req):
        seen.append(req)
        return orig(self, req)

    monkeypatch.setattr(fake_provider.FakeProvider, "stream", stream)
    _, data = auth
    sid = await make()
    comm = await _connect(sid, data["access"])
    await _until(comm, _suggest)  # the host's own explanation turn: no search
    assert seen and not seen[-1].web_search and "You cannot search the web" in seen[-1].system
    await comm.send_json_to({"type": "say", "text": "What is the latest AI news today?"})
    events = await _until(comm, _done)
    await comm.disconnect()
    types = [e["type"] for e in events]
    assert "status" in types and types.index("status") < types.index("delta")
    assert events[-1]["sources"] == [
        {"title": "Example news (demo search)", "url": "https://example.org/news"}
    ]
    req = seen[-1]
    assert req.web_search and "Never search for this workshop's tasks" in req.system
