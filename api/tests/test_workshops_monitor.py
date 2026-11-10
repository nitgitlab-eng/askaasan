"""The live faculty monitor (ws/workshop-runs/<id>/monitor/): auth and teacher scope (on connect, re-auth and every
action), snapshot and tile fan-out through the in-memory channel layer, the 5 s per-learner throttle, status
classification with a frozen clock, nudges to the right learner only, raised hands and their acknowledgement."""

import asyncio
from datetime import timedelta

import pytest
from asgiref.sync import sync_to_async
from channels.layers import channel_layers
from channels.testing import WebsocketCommunicator
from django.core.cache import cache
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User
from apps.orgs.models import Group, Membership, Organization
from apps.workshops import monitor, services
from apps.workshops.content import seed
from apps.workshops.models import Workshop, WorkshopEnrollment, WorkshopEvent, WorkshopRun, WorkshopSession
from config.asgi import application
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db(transaction=True)
HEADERS = [(b"host", b"localhost"), (b"origin", b"http://localhost:5173")]


@pytest.fixture(autouse=True)
def _setup(monkeypatch, settings, db):
    seed()
    settings.CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    channel_layers.backends = {}
    orig = fake_provider.FakeProvider.__init__
    monkeypatch.setattr(fake_provider.FakeProvider, "__init__", lambda self, delay=0.0: orig(self, 0.0))
    yield
    channel_layers.backends = {}


def _user(email, name):
    u = User.objects.create_user(email, "Work#2026passwd")
    u.profile.display_name = name
    u.profile.save()
    return u


def _token(u) -> str:
    return str(AccessToken.for_user(u))


def _school(audience="org", proctoring=""):
    org = Organization.objects.create(
        name="Sunrise", slug="sunrise", features={"workshops": True}, workshop_seats=50
    )
    ga, gb = Group.objects.create(org=org, name="7-A"), Group.objects.create(org=org, name="7-B")
    people = {}
    for key, role, group, name in (
        ("owner", "owner", None, "Meena"),
        ("ta", "manager", ga, "Anitha"),
        ("tb", "manager", gb, "Bala"),
        ("ka", "learner", ga, "Kavya"),
        ("kb", "learner", gb, "Kavin"),
    ):
        u = _user(f"{key}@school.in", name)
        m = Membership.objects.create(org=org, user=u, role=role, fields={"roll_no": key.upper()})
        if group:
            group.members.add(m)
        people[key] = u
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug="quick-check"),
        audience=audience,
        org=org if audience == "org" else None,
        starts_at=timezone.now() - timedelta(minutes=1),
        status="live",
        proctoring=proctoring,
    )
    run.groups.set([ga, gb])
    sessions = {}
    for key in ("ka", "kb"):
        e = WorkshopEnrollment.objects.create(run=run, user=people[key])
        sessions[key] = WorkshopSession.objects.create(enrollment=e, user=people[key], run=run).id
    return {"org": org, "run": run, "ga": ga, "gb": gb, "s": sessions, **people}


school = sync_to_async(_school)


async def _monitor(run_id, user=None, token=None):
    comm = WebsocketCommunicator(application, f"/ws/workshop-runs/{run_id}/monitor/", headers=HEADERS)
    assert (await comm.connect())[0]
    tok = token if token is not None else await sync_to_async(_token)(user)
    await comm.send_json_to({"type": "auth", "token": tok})
    return comm


async def _closed_with(comm, code_str, close_code):
    ev = await comm.receive_json_from(timeout=5)
    assert ev == {"type": "error", "code": code_str}
    out = await comm.receive_output(timeout=5)
    assert out["type"] == "websocket.close" and out["code"] == close_code


async def _snapshot(comm):
    ready = await comm.receive_json_from(timeout=5)
    assert ready["type"] == "ready"
    snap = await comm.receive_json_from(timeout=5)
    assert snap["type"] == "snapshot"
    return ready, snap


# ── Authorisation ────────────────────────────────────────────────────


async def test_monitor_refuses_non_staff_other_org_and_bad_tokens():
    sc = await school()
    run_id = sc["run"].id
    await _closed_with(await _monitor(run_id, sc["ka"]), "forbidden", 4403)  # a learner of the org
    outsider = await sync_to_async(_user)("x@other.in", "X")

    def other_org_admin():
        org = Organization.objects.create(name="Other", slug="other", features={"workshops": True})
        Membership.objects.create(org=org, user=outsider, role="owner")

    await sync_to_async(other_org_admin)()
    await _closed_with(await _monitor(run_id, outsider), "forbidden", 4403)  # staff of another org
    await _closed_with(await _monitor(run_id, token="nope"), "unauthorized", 4401)
    await _closed_with(await _monitor(999999, sc["owner"]), "not_found", 4404)
    # Feature switched off for the org: no dashboard either.
    await sync_to_async(Organization.objects.filter(pk=sc["org"].pk).update)(features={"workshops": False})
    await _closed_with(await _monitor(run_id, sc["owner"]), "feature_off", 4403)


@pytest.mark.parametrize("audience", ["public", "test"])
async def test_public_and_test_runs_have_no_monitor_or_tiles(audience):
    sc = await school(audience=audience)
    await _closed_with(await _monitor(sc["run"].id, sc["owner"]), "no_monitor", 4403)
    assert await sync_to_async(monitor.publish_tile)(sc["s"]["ka"]) is False  # never fanned out


async def test_teacher_snapshot_and_tiles_are_scoped():
    sc = await school()

    def enrolled_not_joined():  # one 7-A and one 7-B learner enrolled who haven't opened a session yet
        for email, name, group in (("kc@school.in", "Charu", sc["ga"]), ("kd@school.in", "Dev", sc["gb"])):
            u = _user(email, name)
            group.members.add(Membership.objects.create(org=sc["org"], user=u, role="learner"))
            WorkshopEnrollment.objects.create(run=sc["run"], user=u)

    await sync_to_async(enrolled_not_joined)()
    comm = await _monitor(sc["run"].id, sc["ta"])
    ready, snap = await _snapshot(comm)
    assert ready["scope"] == "classes"
    assert [t["learner"]["name"] for t in snap["tiles"]] == ["Kavya"]
    assert [x["name"] for x in snap["not_joined"]] == ["Charu"]  # scoped too
    assert snap["tiles"][0]["learner"]["roll_no"] == "KA" and snap["tiles"][0]["status"] == "getting_ready"
    owner = await _monitor(sc["run"].id, sc["owner"])
    ready, snap = await _snapshot(owner)
    assert ready["scope"] == "all" and len(snap["tiles"]) == 2 and snap["run"]["proctoring"] == "off"
    assert sorted(x["name"] for x in snap["not_joined"]) == ["Charu", "Dev"]
    # kb's tile reaches the owner but never the 7-A teacher.
    assert await sync_to_async(monitor.publish_tile)(sc["s"]["kb"])
    got = await owner.receive_json_from(timeout=5)
    assert got["type"] == "tile" and got["tile"]["learner"]["name"] == "Kavin"
    assert await comm.receive_nothing(timeout=0.3)
    assert await sync_to_async(monitor.publish_tile)(sc["s"]["ka"])
    assert (await comm.receive_json_from(timeout=5))["tile"]["session_id"] == sc["s"]["ka"]
    await comm.disconnect()
    await owner.disconnect()


async def test_reauth_rechecks_role_and_scope():
    sc = await school()
    comm = await _monitor(sc["run"].id, sc["ta"])
    await _snapshot(comm)

    # Moved to class 7-B: the re-auth snapshot follows the new scope.
    def move():
        m = Membership.objects.get(org=sc["org"], user=sc["ta"])
        sc["ga"].members.remove(m)
        sc["gb"].members.add(m)

    await sync_to_async(move)()
    await comm.send_json_to({"type": "auth", "token": await sync_to_async(_token)(sc["ta"])})
    _, snap = await _snapshot(comm)
    assert [t["learner"]["name"] for t in snap["tiles"]] == ["Kavin"]
    # Demoted to learner: the next re-auth closes the socket.
    await sync_to_async(Membership.objects.filter(org=sc["org"], user=sc["ta"]).update)(role="learner")
    await comm.send_json_to({"type": "auth", "token": await sync_to_async(_token)(sc["ta"])})
    await _closed_with(comm, "forbidden", 4403)
    # Another account can't take over an open monitor socket.
    owner = await _monitor(sc["run"].id, sc["owner"])
    await _snapshot(owner)
    await owner.send_json_to({"type": "auth", "token": await sync_to_async(_token)(sc["ka"])})
    assert (await owner.receive_json_from(timeout=5))["code"] == "already_authenticated"
    await owner.disconnect()


# ── Fan-out and throttle ─────────────────────────────────────────────


def test_throttle_one_tile_per_5s_per_learner(monkeypatch):
    sc = _school()
    sent = []
    monkeypatch.setattr(monitor, "async_to_sync", lambda f: lambda group, msg: sent.append((group, msg)))
    sid = sc["s"]["ka"]
    assert monitor.publish_tile(sid) is True
    assert monitor.publish_tile(sid) is False  # inside the 5 s window
    assert monitor.publish_tile(sc["s"]["kb"]) is True  # per learner
    assert len(sent) == 2 and sent[0][0] == f"wsrun.{sc['run'].id}" and sent[0][1]["type"] == "wsrun.tile"
    cache.delete(monitor._throttle_key(sid))  # the window ends
    assert monitor.publish_tile(sid) is True
    assert monitor.THROTTLE_SECONDS == 5


async def test_learner_socket_publishes_and_raised_hand_is_sent_after_the_window(monkeypatch):
    monkeypatch.setattr(monitor, "THROTTLE_SECONDS", 1)
    sc = await school()
    owner = await _monitor(sc["run"].id, sc["owner"])
    await _snapshot(owner)
    sid = sc["s"]["ka"]
    learner = WebsocketCommunicator(application, f"/ws/workshop/{sid}/", headers=HEADERS)
    assert (await learner.connect())[0]
    await learner.send_json_to({"type": "auth", "token": await sync_to_async(_token)(sc["ka"])})
    assert (await learner.receive_json_from(timeout=5))["type"] == "ready"
    first = await owner.receive_json_from(timeout=5)  # joining publishes the tile
    assert first["type"] == "tile" and first["tile"]["raised_hand"] is False
    # A hand inside the throttle window is not dropped: it goes out as soon as the window ends.
    await learner.send_json_to({"type": "raise_hand"})
    hand = await owner.receive_json_from(timeout=5)
    assert hand["tile"]["raised_hand"] is True and hand["tile"]["status"] == "needs_help"
    await learner.disconnect()
    await owner.disconnect()


# ── Staff actions ────────────────────────────────────────────────────


async def _learner(sid, user):
    comm = WebsocketCommunicator(application, f"/ws/workshop/{sid}/", headers=HEADERS)
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": await sync_to_async(_token)(user)})
    assert (await comm.receive_json_from(timeout=5))["type"] == "ready"
    return comm


async def test_nudge_reaches_only_that_learner_and_teachers_stay_in_scope():
    sc = await school()
    ka = await _learner(sc["s"]["ka"], sc["ka"])
    kb = await _learner(sc["s"]["kb"], sc["kb"])
    owner = await _monitor(sc["run"].id, sc["owner"])
    await _snapshot(owner)
    text = "<b>Check</b> step 2\x00 please"
    await owner.send_json_to({"type": "nudge", "session_id": sc["s"]["ka"], "text": text})
    assert await owner.receive_json_from(timeout=5) == {
        "type": "ack",
        "action": "nudge",
        "session_id": sc["s"]["ka"],
    }
    got = await ka.receive_json_from(timeout=5)
    nid, at = got.pop("id"), got.pop("at")
    assert got == {"type": "staff_nudge", "text": "<b>Check</b> step 2 please", "from": "Meena"}  # plain text
    assert isinstance(nid, int) and at
    assert await kb.receive_nothing(timeout=0.3)
    ev = await sync_to_async(WorkshopEvent.objects.get)(session_id=sc["s"]["ka"], type="staff_nudge")
    assert ev.data["text"] == "<b>Check</b> step 2 please"
    # Too long, empty, or a session from elsewhere.
    await owner.send_json_to({"type": "nudge", "session_id": sc["s"]["ka"], "text": "x" * 301})
    assert (await owner.receive_json_from(timeout=5))["code"] == "too_long"
    await owner.send_json_to({"type": "nudge", "session_id": sc["s"]["ka"], "text": "  \n "})
    assert (await owner.receive_json_from(timeout=5))["code"] == "empty"
    await owner.send_json_to({"type": "nudge", "session_id": 999999, "text": "hi"})
    assert (await owner.receive_json_from(timeout=5))["code"] == "not_in_scope"
    # The 7-A teacher can't reach a 7-B learner (nudge or ack).
    ta = await _monitor(sc["run"].id, sc["ta"])
    await _snapshot(ta)
    for msg in (
        {"type": "nudge", "session_id": sc["s"]["kb"], "text": "hi"},
        {"type": "ack_hand", "session_id": sc["s"]["kb"]},
    ):
        await ta.send_json_to(msg)
        assert (await ta.receive_json_from(timeout=5))["code"] == "not_in_scope"
    assert await kb.receive_nothing(timeout=0.3)
    # Demoted after connecting: the very next action is refused.
    await sync_to_async(Membership.objects.filter(org=sc["org"], user=sc["ta"]).update)(role="learner")
    await ta.send_json_to({"type": "nudge", "session_id": sc["s"]["ka"], "text": "hi"})
    await _closed_with(ta, "forbidden", 4403)
    for c in (ka, kb, owner):
        await c.disconnect()


async def test_offline_nudges_arrive_in_ready_once():
    sc = await school()
    sid = sc["s"]["ka"]
    owner = await _monitor(sc["run"].id, sc["owner"])
    await _snapshot(owner)
    for text in ("First: open step 2", "Second: ask for help"):
        await owner.send_json_to({"type": "nudge", "session_id": sid, "text": text})
        assert (await owner.receive_json_from(timeout=5))["action"] == "nudge"

    def old_one():  # a nudge from 3 hours ago is stale: not replayed
        s = WorkshopSession.objects.get(pk=sid)
        e = services.event(s, "staff_nudge", text="Stale", by=sc["owner"].id, name="Meena")
        WorkshopEvent.objects.filter(pk=e.pk).update(created_at=timezone.now() - timedelta(hours=3))

    await sync_to_async(old_one)()
    comm = WebsocketCommunicator(application, f"/ws/workshop/{sid}/", headers=HEADERS)
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": await sync_to_async(_token)(sc["ka"])})
    ready = await comm.receive_json_from(timeout=5)
    assert ready["type"] == "ready"
    assert [(n["text"], n["from"]) for n in ready["nudges"]] == [
        ("First: open step 2", "Meena"),
        ("Second: ask for help", "Meena"),
    ]
    assert all(set(n) == {"id", "text", "from", "at"} and isinstance(n["id"], int) for n in ready["nudges"])
    # A nudge sent while connected arrives live and is marked delivered, so it isn't replayed either.
    await owner.send_json_to({"type": "nudge", "session_id": sid, "text": "Live one"})
    for _ in range(5):  # tiles from the learner connecting may come first
        if (await owner.receive_json_from(timeout=5)).get("action") == "nudge":
            break
    for _ in range(5):
        ev = await comm.receive_json_from(timeout=5)
        if ev["type"] == "staff_nudge":
            break
    assert ev["text"] == "Live one" and isinstance(ev["id"], int)

    def delivered():
        return WorkshopEvent.objects.get(pk=ev["id"]).data.get("delivered")

    for _ in range(50):
        if await sync_to_async(delivered)():
            break
        await asyncio.sleep(0.02)
    assert await sync_to_async(delivered)()
    await comm.disconnect()
    comm = WebsocketCommunicator(application, f"/ws/workshop/{sid}/", headers=HEADERS)
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": await sync_to_async(_token)(sc["ka"])})
    ready = await comm.receive_json_from(timeout=5)
    assert ready["type"] == "ready" and ready["nudges"] == []  # everything was delivered already
    await comm.disconnect()
    await owner.disconnect()


def test_pending_nudges_marks_delivered():
    sc = _school()
    s = WorkshopSession.objects.get(pk=sc["s"]["ka"])
    e = services.event(s, "staff_nudge", text="Hi", by=sc["owner"].id, name="Meena")
    other = WorkshopSession.objects.get(pk=sc["s"]["kb"])
    monitor.mark_nudge_delivered(e.id, other.id)  # another session can't mark it
    out = monitor.pending_nudges(s.id)
    assert [n["id"] for n in out] == [e.id] and out[0]["text"] == "Hi"
    assert monitor.pending_nudges(s.id) == []
    assert WorkshopEvent.objects.get(pk=e.pk).data["delivered"] is True


async def test_raise_hand_then_ack_clears_it():
    sc = await school()
    sid = sc["s"]["ka"]

    def raise_hand():
        services.event(services.load(sid), "raise_hand")

    await sync_to_async(raise_hand)()
    owner = await _monitor(sc["run"].id, sc["owner"])
    _, snap = await _snapshot(owner)
    tile = next(t for t in snap["tiles"] if t["session_id"] == sid)
    assert tile["raised_hand"] and tile["status"] == "needs_help"
    await sync_to_async(cache.clear)()
    await owner.send_json_to({"type": "ack_hand", "session_id": sid})
    assert await owner.receive_json_from(timeout=5) == {
        "type": "ack",
        "action": "ack_hand",
        "session_id": sid,
        "changed": True,
    }
    upd = await owner.receive_json_from(timeout=5)
    assert upd["type"] == "tile" and upd["tile"]["raised_hand"] is False
    assert await sync_to_async(WorkshopEvent.objects.filter(session_id=sid, type="hand_ack").count)() == 1
    await owner.send_json_to({"type": "ack_hand", "session_id": sid})  # nothing raised now
    assert (await owner.receive_json_from(timeout=5))["changed"] is False
    await owner.disconnect()


# ── Classification (frozen clock) ────────────────────────────────────


def _classify_case(setup):
    """A started session at T, events placed at given offsets; → classify(session, events, now)."""
    sc = _school(proctoring=setup.get("proctoring", ""))
    s = WorkshopSession.objects.get(pk=sc["s"]["ka"])
    T = timezone.now() - timedelta(minutes=30)
    s.prereqs_done = {p["key"]: "x" for p in s.run.workshop.prerequisites}
    s.save()
    if setup.get("started", True):
        services.start(s)
        WorkshopSession.objects.filter(pk=s.pk).update(
            started_at=T,
            planned_end=T + timedelta(minutes=10),
            grace_end=T + timedelta(minutes=40),
            last_activity_at=T,
        )
        WorkshopEvent.objects.filter(session=s).update(created_at=T)
    s = services.load(s.id)
    for f, v in setup.get("fields", {}).items():
        setattr(s, f, v)
    for typ, minutes, data in setup.get("events", []):
        e = WorkshopEvent.objects.create(session=s, type=typ, stage=s.stage_index, data=data)
        WorkshopEvent.objects.filter(pk=e.pk).update(created_at=T + timedelta(minutes=minutes))
    if setup.get("stage") is not None:
        s.stage_index = setup["stage"]
    if "items" in setup:
        services.state(s)["items"][0].update(setup["items"])
    s.save()
    now = T + timedelta(minutes=setup.get("now", 5))
    events = monitor.recent_events(s)
    return monitor.classify(s, events, now)


# quick-check agenda: stage 0 teach, stage 1 diy, stage 2 assessment; planned 10 min, grace to 40 min.
CASES = {
    "getting_ready": {"started": False},
    "engaged": {"now": 1},
    "doing_diy": {"stage": 1, "now": 1, "events": [("stage_start", 0.5, {})]},
    "idle": {"now": 3, "events": [("stage_start", 0, {})]},
    "away": {"proctoring": "activity", "now": 1, "fields": {"stage_state": {"_att": {"hidden_at": "x"}}}},
    "stuck": {"now": 2, "items": {"explained": True, "tries": 3, "score": 0.5}},
    "needs_help": {"now": 2, "events": [("help_error", 1, {"summary": "pip failed"})]},
    # (a raised hand on the prerequisites screen also needs help: see test_classify_rules)
    "in_grace": {"now": 12, "events": [("answer", 11, {"item": 0, "score": 0.9})]},
    "overtime": {"now": 45, "events": [("answer", 44, {"item": 0, "score": 0.9})]},
    "finished": {"fields": {"status": "submitted"}},
    "passed": {"fields": {"status": "submitted", "passed": True}},
}


@pytest.mark.parametrize("expected", list(CASES))
def test_classify_every_status(expected):
    assert _classify_case(CASES[expected]) == expected


@pytest.mark.parametrize(
    "setup,expected",
    [
        # Away needs proctoring on and a non-DIY stage.
        ({"now": 1, "fields": {"stage_state": {"_att": {"hidden_at": "x"}}}}, "engaged"),
        (
            {
                "proctoring": "activity",
                "stage": 1,
                "now": 1,
                "events": [("stage_start", 0.5, {})],
                "fields": {"stage_state": {"_att": {"hidden_at": "x"}}},
            },
            "doing_diy",
        ),
        # Idle never applies in DIY; no progress for >10 min in DIY is stuck, 9 min is not.
        ({"stage": 1, "now": 9, "events": [("stage_start", 0, {})]}, "doing_diy"),
        ({"stage": 1, "now": 11, "events": [("stage_start", 0, {})]}, "stuck"),
        # No progress for >8 min outside DIY (even while chatting) is stuck.
        ({"now": 9, "events": [("stage_start", 0, {}), ("raise_hand", 1, {}), ("hand_ack", 2, {})]}, "stuck"),
        # The same help error twice (older than the 5 min help window) is stuck.
        (
            {
                "now": 9,
                "events": [
                    ("help_error", 1, {"summary": "Pip failed!"}),
                    ("help_error", 2, {"summary": "pip failed"}),
                    ("answer", 3, {"item": 0, "score": 0.9}),
                ],
            },
            "stuck",
        ),
        # Two low scores in a row → needs help; a raised hand (unacknowledged) → needs help.
        (
            {
                "now": 2,
                "events": [
                    ("answer", 1, {"item": 0, "score": 0.1}),
                    ("answer", 1.5, {"item": 0, "score": 0.2}),
                ],
            },
            "needs_help",
        ),
        ({"now": 2, "events": [("raise_hand", 1, {})]}, "needs_help"),
        ({"now": 2, "events": [("raise_hand", 1, {}), ("hand_ack", 1.5, {})]}, "engaged"),
        ({"started": False, "events": [("raise_hand", 1, {})]}, "needs_help"),
        ({"started": False, "events": [("raise_hand", 1, {}), ("hand_ack", 2, {})]}, "getting_ready"),
    ],
)
def test_classify_rules(setup, expected):
    assert _classify_case(setup) == expected


def test_tile_shape_and_attention_only_with_proctoring():
    sc = _school(proctoring="activity")
    s = services.load(sc["s"]["ka"])
    s.prereqs_done = {p["key"]: "x" for p in s.run.workshop.prerequisites}
    s.save()
    services.start(s)
    for i in range(4):
        services.event(s, "help_error", summary=f"error {i}")
    t = monitor.tile(services.load(s.id))
    assert set(t) == {
        "session_id",
        "learner",
        "status",
        "stage",
        "concept",
        "diy",
        "score_so_far",
        "final_score",
        "passed",
        "attention",
        "help_summaries",
        "raised_hand",
        "last_activity_at",
        "pace",
    }
    assert t["help_summaries"] == ["error 3", "error 2", "error 1"]  # ≤3, newest first
    assert t["attention"] == {"hidden_s": 0, "idle_s": 0, "focus_losses": 0}
    assert t["stage"]["kind"] == "teach" and t["concept"] and t["pace"] == "on_track"
    WorkshopRun.objects.filter(pk=sc["run"].pk).update(proctoring="off")
    assert monitor.tile(services.load(s.id))["attention"] is None


def test_nudge_text_rules():
    assert monitor.clean_nudge("hi\tthere\r\n") == ("hi there", None)
    assert monitor.clean_nudge("x" * 300)[1] is None
    assert monitor.clean_nudge("x" * 301) == (None, "too_long")
    assert monitor.clean_nudge(None) == (None, "empty")
    assert monitor.clean_nudge({"a": 1}) == (None, "empty")


async def test_nudge_rate_limit(monkeypatch):
    from apps.workshops import consumers

    monkeypatch.setattr(consumers, "NUDGES_PER_MINUTE", 2)
    sc = await school()
    owner = await _monitor(sc["run"].id, sc["owner"])
    await _snapshot(owner)
    codes = []
    for _ in range(3):
        await owner.send_json_to({"type": "nudge", "session_id": sc["s"]["ka"], "text": "hi"})
        ev = await owner.receive_json_from(timeout=5)
        codes.append(ev.get("code") or ev["type"])
    assert codes == ["ack", "ack", "rate_limited"]
    await asyncio.sleep(0)
    await owner.disconnect()
