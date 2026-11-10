"""Live AI Workshop: consent-based advance, suggested replies, interruptions, stop reasons, quiet check-ins and the
workshop voice preference (CONTRACT-LIVE). Fake provider only."""

import asyncio
from types import SimpleNamespace

import pytest
from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.preferences import default_preferences, upgrade
from apps.accounts.serializers import validate_preferences_patch
from apps.workshops import consumers, services
from apps.workshops.content import seed
from apps.workshops.models import (
    Workshop,
    WorkshopEnrollment,
    WorkshopEvent,
    WorkshopRun,
    WorkshopSession,
    WorkshopTurn,
)
from config.asgi import application
from llm.base import StreamEvent
from llm.providers import fake_provider

# ── helpers ──────────────────────────────────────────────────────────


def _make(email="kavya@example.com", slug="quick-check", started=True):
    user = User.objects.get(email=email)
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug=slug),
        audience="test",
        starts_at=services.now(),
        status="live",
        created_by=user,
    )
    e = WorkshopEnrollment.objects.create(run=run, user=user)
    s = WorkshopSession.objects.create(enrollment=e, user=user, run=run)
    if started:
        s.prereqs_done = {p["key"]: "x" for p in run.workshop.prerequisites}
        s.save()
        assert services.start(s) is None
    return s.id


def _explain(sid, stage=None, item=None):
    s = services.load(sid)
    st = services.state(s, stage)
    services.after_turn(
        sid,
        "Like a shop assistant learning tomatoes. Can you say it back?",
        ("explained", s.stage_index if stage is None else stage, st["cursor"] if item is None else item),
    )


def _pass(sid):
    """Explain the current concept and answer its check well (the fake check scores 0.9)."""
    _explain(sid)
    return services.on_say(sid, "It learns patterns from lots of examples, like my aunt picking mangoes.")


def _cur(sid):
    s = services.load(sid)
    return s, services.state(s)


# ── service level ────────────────────────────────────────────────────

db = pytest.mark.django_db


@pytest.fixture
def seeded(db):
    seed()


@db
def test_yes_next_needs_ready_to_move_then_advances(auth, seeded):
    sid = _make()
    assert services.on_control(sid, "yes_next").error == "not_ready"  # nothing explained yet
    _explain(sid)
    assert services.on_control(sid, "yes_next").error == "not_ready"  # explained, not yet checked
    s, st = _cur(sid)
    assert not services.ready_to_move(s) and services.session_out(s)["stages"][0]["ready_to_move"] is False
    out = _pass(sid)
    assert out.progress and "Shall we move on?" in out.note
    s, st = _cur(sid)
    assert st["items"][0]["ready_to_move"] and services.session_out(s)["stages"][0]["ready_to_move"] is True
    assert st["cursor"] == 0  # still never moves by itself
    out = services.on_control(sid, "yes_next")
    assert out.progress and out.after == ("explained", 0, 1)
    s, st = _cur(sid)
    assert st["cursor"] == 1 and not services.ready_to_move(s)
    assert services.on_control(sid, "yes_next").error == "not_ready"  # the new concept starts over


@db
def test_three_tries_also_makes_ready(auth, seeded, monkeypatch):
    sid = _make()
    _explain(sid)
    monkeypatch.setitem(
        fake_provider.CANNED, "[[TASK:workshop_check]]", {"answered": True, "score": 0.1, "note": "vague"}
    )
    for _ in range(3):
        out = services.on_say(sid, "no idea really")
    assert "three times" in out.note and "Shall we move on?" in out.note
    assert services.ready_to_move(services.load(sid))


@db
def test_yes_next_allowed_while_ai_paused(auth, seeded, settings):
    sid = _make()
    settings.WORKSHOP_SESSION_AI_UNITS = 5
    WorkshopSession.objects.filter(pk=sid).update(ai_units=5)
    assert services.on_control(sid, "yes_next").progress  # a pause never traps the learner


@pytest.mark.parametrize(
    "text",
    ["yes", "Yes!", "ok next", "okay, move on", "move on", "Sari", "seri da", "aama", "aduthu", "சரி", "ஆமா",
     "அடுத்து", "போகலாம்", "yes please", "continue", "Let's go ahead"],
)  # fmt: skip
def test_consent_words(text):
    assert services.is_consent(text)


@pytest.mark.parametrize(
    "text",
    ["no", "not yet", "", "yes but what is a token", "ok so why does it guess words", "I am not sure",
     "yes yes yes yes yes", "on", "please", "next week maybe"],
)  # fmt: skip
def test_not_consent(text):
    assert not services.is_consent(text)


@db
def test_spoken_yes_moves_on_only_when_ready(auth, seeded):
    sid = _make()
    _explain(sid)
    out = services.on_say(sid, "yes")  # not ready: an ordinary answer to the check, not a skip
    s, st = _cur(sid)
    assert out.error is None and st["cursor"] == 0
    assert st["items"][0]["done"] and st["items"][0]["ready_to_move"]  # (the fake check passes everything)
    out = services.on_say(sid, "சரி")
    s, st = _cur(sid)
    assert out.progress and st["cursor"] == 1
    said = list(WorkshopTurn.objects.filter(session_id=sid, role="user").values_list("text", flat=True))
    assert said[-1] == "சரி"  # the consent stays in the transcript


@db
def test_not_yet_keeps_ready_and_gives_another_example(auth, seeded):
    sid = _make()
    _pass(sid)
    out = services.on_control(sid, "not_yet")
    assert "NOT YET" in out.note and "Shall we move on?" in out.note and "<concept>" in out.note
    s, st = _cur(sid)
    assert st["cursor"] == 0 and services.ready_to_move(s)  # always possible to say yes next
    assert services.suggest(sid) == ["yes_next", "not_yet"]


@db
def test_not_sure_re_explains_and_reasks(auth, seeded):
    sid = _make()
    _explain(sid)
    out = services.on_control(sid, "not_sure")
    assert "NOT SURE" in out.note and "smaller" in out.note
    assert out.after == (
        "question",
        0,
        0,
    )  # the new question becomes the one the next answer is checked against
    services.after_turn(sid, "Simpler: what does the shop assistant learn from?", out.after)
    assert services.state(services.load(sid))["last_q"].startswith("Simpler")


@db
def test_stuck_on_diy_asks_for_screenshot_elsewhere_like_not_sure(auth, seeded):
    sid = _make()
    _explain(sid)
    out = services.on_control(sid, "stuck")
    assert "STUCK" in out.note and "smaller" in out.note and "screenshot" not in out.note
    WorkshopSession.objects.filter(pk=sid).update(stage_index=1)  # quick-check: stage 1 is DIY
    out = services.on_control(sid, "stuck")
    assert "screenshot" in out.note and "paste the error" in out.note and "<step>" in out.note
    assert out.after is None


@db
def test_continue_picks_up_a_cut_off_reply(auth, seeded):
    sid = _make()
    out = services.on_control(sid, "continue")
    assert "cut off" in out.note and out.after is None
    _pass(sid)
    assert "Shall we move on?" in services.on_control(sid, "continue").note


@db
def test_unknown_controls_are_refused(auth, seeded):
    sid = _make()
    for bad in ("dance", "__init__", "YES_NEXT", "submit", ""):
        assert services.on_control(sid, bad).error == "bad_control"


@db
def test_suggest_chips_follow_the_state(auth, seeded):
    sid = _make()
    assert services.suggest(sid) == []  # nothing explained yet
    _explain(sid)
    assert services.suggest(sid) == ["not_sure", "example", "tamil"]
    services.on_control(sid, "tamil")
    assert services.suggest(sid) == ["not_sure", "example", "english"]
    assert services.suggest(sid, "max_tokens") == ["continue", "not_sure", "example"]  # ≤ 3, continue first
    _pass(sid)
    assert services.suggest(sid) == ["yes_next", "not_yet"]
    assert services.suggest(sid, "max_tokens") == ["continue", "yes_next", "not_yet"]
    WorkshopSession.objects.filter(pk=sid).update(stage_index=1)  # DIY
    assert services.suggest(sid) == ["done", "stuck"]
    services.on_step_done(sid, 0)
    assert services.suggest(sid) == ["yes_next", "not_yet"]  # a ticked step is ready to move on
    services.on_control(sid, "yes_next")
    s = services.load(sid)
    assert services.stage(s)["kind"] == "assessment" and services.suggest(sid) == []
    assert services.suggest(sid, "max_tokens") == []  # no chips during the final
    WorkshopSession.objects.filter(pk=sid).update(status="submitted")
    assert services.suggest(sid) == []
    assert all(set(services.suggest(sid, r)) <= set(services.CHIPS) for r in ("end_turn", "max_tokens"))


@db
def test_suggest_empty_before_start(auth, seeded):
    sid = _make(started=False)
    assert services.suggest(sid) == [] and not services.ready_to_move(services.load(sid))


@db
def test_cancelled_partial_does_not_count_and_stays_out_of_context(auth, seeded):
    sid = _make()
    services.on_say(sid, "hello")
    changed = services.after_turn(sid, "Think of a prompt like ord", ("explained", 0, 0), cancelled=True)
    s, st = _cur(sid)
    assert not changed and not st["items"][0]["explained"] and "last_q" not in st
    t = WorkshopTurn.objects.filter(session_id=sid, role="assistant").last()
    assert t.cancelled and t.text == "Think of a prompt like ord"
    assert services.recent_turns(s)[-1]["cancelled"] is True  # flagged in ready.turns
    assert services.recent_turns(s)[0]["cancelled"] is False
    services.on_say(sid, "sorry, go on")
    _, history = services.host_context(sid, False)
    texts = [m.content for m in history]
    assert "Think of a prompt like ord" not in "".join(texts)
    # Consecutive learner turns stay separate messages (no "\n\n" stitching).
    assert texts[:2] == ["hello", "sorry, go on"] and all(m.role == "user" for m in history[:2])
    assert history[-1].role == "assistant"  # the director note follows as the next user message
    assert services.suggest(sid) == []  # the item still needs its (complete) explanation


def test_host_max_tokens_raised():
    assert services.HOST_MAX_TOKENS == 1500


def test_stop_reason_normalised():
    assert consumers.stop_reason("max_tokens") == "max_tokens"
    assert consumers.stop_reason("length") == "max_tokens"  # OpenAI
    assert consumers.stop_reason("end_turn") == "end_turn"
    assert consumers.stop_reason("stop") == "end_turn"
    assert consumers.stop_reason(None) == "end_turn"
    assert consumers.stop_reason("refusal") == "end_turn"


async def test_gemini_reports_max_tokens():
    from google.genai import types

    from llm.base import ChatMessage, LLMRequest
    from llm.providers import gemini_provider

    def chunk(text, finish=None):
        cands = [SimpleNamespace(finish_reason=finish)] if finish else []
        return SimpleNamespace(text=text, usage_metadata=None, candidates=cands)

    def client_for(chunks):
        async def gen():
            for c in chunks:
                yield c

        async def generate_content_stream(**kw):
            return gen()

        return SimpleNamespace(
            aio=SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate_content_stream))
        )

    req = LLMRequest(model="m", system="s", messages=[ChatMessage("user", "hi")], max_tokens=5)
    for finish, expected in (
        (types.FinishReason.MAX_TOKENS, "max_tokens"),
        (types.FinishReason.STOP, "end_turn"),
    ):
        p = gemini_provider.GeminiProvider.__new__(gemini_provider.GeminiProvider)
        p.client = client_for([chunk("Vanakkam "), chunk("da", finish)])
        events = [ev async for ev in p.stream(req)]
        assert "".join(e.delta for e in events) == "Vanakkam da"
        assert events[-1].done and events[-1].stop_reason == expected


# ── preferences ──────────────────────────────────────────────────────


def test_workshop_voice_mode_preference():
    assert default_preferences()["voice"] == {
        "workshop_mode": "tap",
        "mentor_mode": "tap",
        "mentor_read_aloud": True,
        "mentor_lang": "",
    }
    assert upgrade({"version": 2})["voice"]["workshop_mode"] == "tap"  # old rows get the default
    out = validate_preferences_patch({}, {"voice": {"workshop_mode": "handsfree"}})
    assert out["voice"]["workshop_mode"] == "handsfree"
    for bad in ({"workshop_mode": "loud"}, {"workshop_mode": ""}, {"workshop_mode": 1}, {"other": "x"}):
        with pytest.raises(serializers.ValidationError):
            validate_preferences_patch({}, {"voice": bad})


@db
def test_workshop_voice_mode_over_the_api(auth):
    client, _ = auth
    r = client.get("/api/users/preferences/")
    assert r.data["voice"]["workshop_mode"] == "tap"
    r = client.patch("/api/users/preferences/", {"voice": {"workshop_mode": "handsfree"}}, format="json")
    assert r.status_code == 200 and r.data["voice"]["workshop_mode"] == "handsfree"
    r = client.patch("/api/users/preferences/", {"voice": {"workshop_mode": "always"}}, format="json")
    assert r.status_code == 400


# ── over the socket ──────────────────────────────────────────────────

ws = pytest.mark.django_db(transaction=True)
DELAY = {"s": 0.0}


@pytest.fixture
def live(monkeypatch, db):
    seed()
    DELAY["s"] = 0.0
    orig = fake_provider.FakeProvider.__init__
    monkeypatch.setattr(
        fake_provider.FakeProvider, "__init__", lambda self, delay=0.0: orig(self, DELAY["s"])
    )


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


def _is(kind):
    return lambda e: e["type"] == kind


@ws
async def test_ready_carries_suggest_and_chips_follow_each_turn(auth, live):
    _, data = auth
    sid = await make()
    comm = await _connect(sid, data["access"])
    ready = (await _until(comm, _is("ready")))[-1]
    assert ready["suggest"] == [] and all("cancelled" in t for t in ready["turns"])
    seen = await _until(comm, _is("suggest"))
    assert any(e["type"] == "done" and e["stop_reason"] == "end_turn" for e in seen)
    assert seen[-1]["chips"] == ["not_sure", "example", "tamil"]
    await comm.send_json_to({"type": "control", "action": "yes_next"})
    assert (await comm.receive_json_from()) == {"type": "error", "code": "not_ready"}
    # A refused tap re-sends the chips for this moment, so stale ones never stay on screen.
    assert (await comm.receive_json_from()) == {"type": "suggest", "chips": ["not_sure", "example", "tamil"]}
    await comm.send_json_to(
        {"type": "say", "text": "It learns patterns from examples, like picking mangoes."}
    )
    seen = await _until(comm, _is("suggest"))
    assert seen[-1]["chips"] == ["yes_next", "not_yet"]
    await comm.send_json_to({"type": "control", "action": "not_yet"})
    seen = await _until(comm, _is("suggest"))
    assert seen[0]["type"] == "start" and seen[-1]["chips"] == ["yes_next", "not_yet"]
    await comm.send_json_to({"type": "say", "text": "ok next"})  # spoken consent
    seen = await _until(comm, _is("suggest"))
    prog = next(e for e in seen if e["type"] == "progress")
    assert prog["session"]["stages"][0]["cursor"] == 1
    await comm.send_json_to({"type": "control", "action": "dance"})
    assert (await comm.receive_json_from())["code"] == "bad_control"
    await comm.disconnect()


@ws
async def test_say_mid_turn_cancels_then_answers_without_busy(auth, live):
    _, data = auth
    sid = await make()
    DELAY["s"] = 0.05  # the opening explanation takes a couple of seconds
    comm = await _connect(sid, data["access"])
    await _until(comm, _is("delta"))
    await comm.send_json_to({"type": "say", "text": "wait, what is a model?"})
    seen = await _until(comm, _is("suggest"))
    kinds = [e["type"] for e in seen]
    assert not any(e.get("code") == "busy" for e in seen)
    cancel_at = seen.index({"type": "done", "stop_reason": "cancelled"})
    assert "start" in kinds[cancel_at:]  # the new input is answered after the clean cancel
    assert [e for e in seen if e["type"] == "done"][-1]["stop_reason"] == "end_turn"

    @sync_to_async
    def check():
        turns = list(WorkshopTurn.objects.filter(session_id=sid).order_by("id"))
        assert [(t.role, t.cancelled) for t in turns] == [
            ("assistant", True),
            ("user", False),
            ("assistant", False),
        ]
        s, st = _cur(sid)
        # The interrupted partial doesn't count, but the reply to the learner answers them and then explains the item
        # (so they are never left without an explanation or chips); that completed reply marks it explained.
        assert turns[0].cancelled and st["items"][0]["explained"]
        _, history = services.host_context(sid, False)
        assert [m.role for m in history] == ["user", "assistant"]  # the partial is left out
        assert history[0].content == "wait, what is a model?" and history[1].content == turns[2].text

    await check()
    await comm.disconnect()


@ws
async def test_control_mid_turn_also_interrupts(auth, live):
    _, data = auth
    sid = await make()
    DELAY["s"] = 0.05
    comm = await _connect(sid, data["access"])
    await _until(comm, _is("delta"))
    await comm.send_json_to({"type": "control", "action": "slower"})
    seen = await _until(comm, _is("suggest"))
    assert {"type": "done", "stop_reason": "cancelled"} in seen
    assert not any(e.get("code") == "busy" for e in seen)
    assert await WorkshopTurn.objects.filter(session_id=sid, cancelled=True).acount() == 1
    await comm.disconnect()


@ws
async def test_max_tokens_is_surfaced_with_continue_chip(auth, live, monkeypatch):
    _, data = auth
    sid = await make()

    async def stream(self, req):
        assert req.max_tokens == services.HOST_MAX_TOKENS
        yield StreamEvent(delta="Think of a prompt like ordering at a hotel, where")
        yield StreamEvent(done=True, stop_reason="length", model="fake")

    monkeypatch.setattr(fake_provider.FakeProvider, "stream", stream)
    comm = await _connect(sid, data["access"])
    seen = await _until(comm, _is("suggest"))
    assert any(e["type"] == "done" and e["stop_reason"] == "max_tokens" for e in seen)
    assert seen[-1]["chips"][0] == "continue" and len(seen[-1]["chips"]) <= 3
    await comm.send_json_to({"type": "control", "action": "continue"})
    seen = await _until(comm, _is("suggest"))
    assert seen[0]["type"] == "start"
    await comm.disconnect()


@ws
async def test_quiet_check_in_once_per_item(auth, live, monkeypatch):
    _, data = auth
    sid = await make()
    monkeypatch.setattr(consumers, "CLOCK_EVERY", 0.05)
    monkeypatch.setattr(consumers, "QUIET_AFTER", 0.2)
    comm = await _connect(sid, data["access"])
    await _until(comm, _is("suggest"))  # the opening explanation
    seen = await _until(comm, _is("suggest"))  # the check-in: a short host turn
    assert any(e["type"] == "start" for e in seen)
    # Quiet for much longer: no second check-in on this item, only pace ticks.
    later = []
    end = asyncio.get_event_loop().time() + 1.0
    while asyncio.get_event_loop().time() < end:
        try:
            later.append(await comm.receive_json_from(timeout=0.2))
        except TimeoutError:
            pass
    assert not any(e["type"] == "start" for e in later)
    events = await WorkshopEvent.objects.filter(session_id=sid, type="check_in").acount()
    assert events == 1
    s = await sync_to_async(services.load)(sid)
    assert s.stage_index == 0 and services.state(s)["cursor"] == 0  # never a cutoff or a move
    await comm.disconnect()


@ws
async def test_learner_input_resets_the_quiet_timer(auth, live, monkeypatch):
    _, data = auth
    sid = await make()
    monkeypatch.setattr(consumers, "CLOCK_EVERY", 0.05)
    monkeypatch.setattr(consumers, "QUIET_AFTER", 30.0)
    comm = await _connect(sid, data["access"])
    await _until(comm, _is("suggest"))
    await asyncio.sleep(0.3)
    assert not await WorkshopEvent.objects.filter(session_id=sid, type="check_in").aexists()
    await comm.disconnect()


def test_learner_speaking_before_an_explanation_gets_answered_then_taught(auth, seeded):
    """e2e run: the learner typed during the opening explanation, the opening was cancelled, and the item stayed
    unexplained with no chips. Now a reply answers them, then explains the item, which unlocks the check + chips."""
    sid = _make()
    s = services.load(sid)
    st = services.state(s)
    assert not st["items"][st["cursor"]]["explained"]
    out = services.on_say(sid, "AI learns patterns from lots of examples.")
    assert out.after and out.after[0] == "explained"
    assert "before you finished explaining" in out.note
    services.after_turn(sid, "Good thought! Here's the idea: ...", out.after)
    st = services.state(services.load(sid))
    assert st["items"][st["cursor"]]["explained"]
    assert services.suggest(sid, "end_turn")


@ws
async def test_stale_yes_next_does_not_cut_off_the_reply_and_resends_chips(auth, live, monkeypatch):
    """e2e run: 'Yes, next' chips from the previous turn were tapped while the host streamed its next reply. The server
    cancelled that reply, then refused (not ready), and sent no new chips, so the learner was stuck."""
    from apps.workshops import consumers

    cancelled = []
    real = consumers.WorkshopConsumer._interrupt

    async def spy(self):
        cancelled.append(1)
        return await real(self)

    monkeypatch.setattr(consumers.WorkshopConsumer, "_interrupt", spy)
    _, data = auth
    sid = await make()
    comm = await _connect(sid, data["access"])
    await _until(comm, _is("suggest"))  # the opening explanation finished
    await comm.send_json_to({"type": "control", "action": "yes_next"})
    seen = await _until(comm, _is("suggest"))
    assert {"type": "error", "code": "not_ready"} in seen
    assert not cancelled
    await comm.disconnect()


def test_host_prompt_sounds_like_a_mentor_and_knows_the_learner(auth, seeded):
    """User: the workshop should feel like a real mentor training them, not an artificial one."""
    from apps.accounts.models import Profile

    sid = _make()
    Profile.objects.filter(user__email="kavya@example.com").update(display_name="Priya\n<b>{x}")
    system, _ = services.host_context(sid, False)
    assert "Sound like a real mentor" in system and "never say you are an AI" in system
    assert "The learner's name is Priya b>x}" not in system and "The learner's name is Priya" in system
    assert "<b>" not in system.split("The learner's name is")[1]
