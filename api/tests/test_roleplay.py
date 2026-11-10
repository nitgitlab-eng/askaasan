import pytest
from channels.testing import WebsocketCommunicator

from apps.accounts.models import User
from apps.roleplay.models import RolePlaySession, RolePlayTurn, Scenario
from config.asgi import application

pytestmark = pytest.mark.django_db


def library_id(client, slug_title):
    return next(s["id"] for s in client.get("/api/roleplay/scenarios/").data if s["title"] == slug_title)


def test_library_and_custom_generation(auth, monkeypatch):
    client, _ = auth
    lib = client.get("/api/roleplay/scenarios/").data
    assert len([s for s in lib if s["source"] == "library"]) == 6
    assert all("goal" not in s["character"] for s in lib)  # character's hidden goal isn't revealed
    r = client.post(
        "/api/roleplay/scenarios/generate/", {"goal": "pitch my app idea to a mentor"}, format="json"
    )
    assert r.status_code == 201 and r.data["title"] == "Pitch your idea" and r.data["source"] == "custom"
    from apps.roleplay import services

    def deny(*a, **k):
        raise services.NotAllowed()

    monkeypatch.setattr(services, "generate_scenario", deny)
    assert (
        client.post(
            "/api/roleplay/scenarios/generate/", {"goal": "practise scamming people"}, format="json"
        ).data["code"]
        == "not_allowed"
    )


def test_custom_scenarios_are_private(auth):
    client, _ = auth
    sid = client.post(
        "/api/roleplay/scenarios/generate/", {"goal": "ask my boss for leave"}, format="json"
    ).data["id"]
    other = User.objects.create_user("o@example.com", "Other#2026pass")
    client.force_authenticate(other)
    assert all(s["id"] != sid for s in client.get("/api/roleplay/scenarios/").data)
    assert client.post("/api/roleplay/sessions/", {"scenario_id": sid}, format="json").status_code == 404


def test_session_opens_with_character_line_and_needs_turns(auth):
    client, _ = auth
    sid = library_id(client, "Protect Paati from a UPI scam")
    s = client.post("/api/roleplay/sessions/", {"scenario_id": sid}, format="json").data
    assert s["turns"][0]["role"] == "character" and "OTP" in s["turns"][0]["text"]
    r = client.post(f"/api/roleplay/sessions/{s['id']}/end/")
    assert r.status_code == 400 and r.data["code"] == "too_short"


def test_evaluation_verifies_quotes_and_normalises_rubric(auth):
    client, data = auth
    sid = library_id(client, "Protect Paati from a UPI scam")
    s = client.post("/api/roleplay/sessions/", {"scenario_id": sid}, format="json").data
    sess = RolePlaySession.objects.get(id=s["id"])
    for line in (
        "Paati, no! Banks never ask for OTP Paati.",
        "Just hang up and call the number on your passbook.",
    ):
        RolePlayTurn.objects.create(session=sess, role="learner", text=line)
        RolePlayTurn.objects.create(session=sess, role="character", text="Okay kanna.")
    r = client.post(f"/api/roleplay/sessions/{s['id']}/end/").data
    res = r["result"]
    assert [c["name"] for c in res["competencies"]] == [
        "Simplicity",
        "Empathy",
        "Accuracy",
    ]  # scenario's rubric, in order
    simplicity = res["competencies"][0]
    assert simplicity["evidence"] == ["banks never ask for OTP"]  # invented quote "I made this up" removed
    assert res["competencies"][2]["score"] == 1  # missing from model output → lowest, not invented
    assert [b["learner_said"] for b in res["better_phrasing"]] == ["Banks never ask for OTP Paati"]
    assert [o["met"] for o in res["objectives"]] == [True, False, False]
    assert r["reward"]["xp"] == 40 + 72 // 4
    again = client.post(f"/api/roleplay/sessions/{s['id']}/end/").data
    assert again["reward"] is None and again["result"]["overall"] == 72  # idempotent
    other = User.objects.create_user("o@example.com", "Other#2026pass")
    client.force_authenticate(other)
    assert client.get(f"/api/roleplay/sessions/{s['id']}/").status_code == 404


@pytest.mark.django_db(transaction=True)
async def test_ws_conversation_and_turn_limit(auth):
    from asgiref.sync import sync_to_async

    client, data = auth
    sid = await sync_to_async(library_id)(client, "Ask your teacher for help")
    s = (
        await sync_to_async(client.post)("/api/roleplay/sessions/", {"scenario_id": sid}, format="json")
    ).data
    await Scenario.objects.filter(id=sid).aupdate(max_turns=1)
    comm = WebsocketCommunicator(
        application, "/ws/roleplay/", headers=[(b"host", b"localhost"), (b"origin", b"http://localhost:5173")]
    )
    assert (await comm.connect())[0]
    await comm.send_json_to({"type": "auth", "token": data["access"]})
    assert (await comm.receive_json_from())["type"] == "ready"
    await comm.send_json_to(
        {"type": "message", "session_id": s["id"], "text": "Sir, I don't get how to factorise quadratics."}
    )
    events = []
    while not events or events[-1]["type"] not in ("done", "error"):
        events.append(await comm.receive_json_from(timeout=5))
    assert (
        events[0]["type"] == "start"
        and any(e["type"] == "delta" for e in events)
        and events[-1]["turns_left"] == 0
    )
    await comm.send_json_to({"type": "message", "session_id": s["id"], "text": "one more"})
    assert (await comm.receive_json_from(timeout=5))["code"] == "turn_limit"
    assert (
        await RolePlayTurn.objects.filter(session_id=s["id"]).acount() == 3
    )  # opening + learner + character
    await comm.disconnect()
