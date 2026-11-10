"""M10 rpx: role-play live coach — per-turn tracker, Kili's hints, fact checks, permissions and the daily cap."""

import pytest
from django.test import override_settings

from apps.accounts.models import User
from apps.orgs.models import Membership, Organization
from apps.roleplay import coach
from apps.roleplay.models import RolePlaySession, RolePlayTurn, Scenario
from llm.prompts.roleplay import FactCheck

pytestmark = pytest.mark.django_db

FACTS = ["The restaurant bill was ₹1,240.", "Refunds are allowed within 7 days."]


def _scenario(owner, **kw):
    return Scenario.objects.create(
        owner=owner,
        title="Settle the bill",
        summary="A customer disputes a restaurant bill of ₹1,240.",
        learner_role="A restaurant manager",
        character={"name": "Ravi", "persona": "an upset diner", "goal": "get a discount", "style": "brisk"},
        setting="A busy Chennai restaurant",
        objectives=["Confirm the bill amount", "Offer a fair solution"],
        competencies=[
            {"name": "Accuracy", "description": "gets facts right"},
            {"name": "Calm", "description": "stays calm"},
        ],
        opening_line="This bill is wrong!",
        **kw,
    )


def _session(client, owner):
    sc = _scenario(owner)
    r = client.post("/api/roleplay/sessions/", {"scenario_id": sc.id}, format="json")
    assert r.status_code == 201
    return RolePlaySession.objects.get(id=r.data["id"])


def _say(s, text, reply="Hmm, okay."):
    RolePlayTurn.objects.create(session=s, role="learner", text=text)
    RolePlayTurn.objects.create(session=s, role="character", text=reply)


def test_tracker_updates_per_turn_and_persists(auth):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    empty = client.get(f"/api/roleplay/sessions/{s.id}/").data["coach"]
    assert [o["score"] for o in empty["objectives"]] == [0, 0] and empty["hints_left"] == 3
    _say(s, "Sir, let me check the bill with you.")
    st = client.post(f"/api/roleplay/sessions/{s.id}/coach/").data
    assert [o["score"] for o in st["objectives"]] == [2, 3]  # 7 clamped to 3
    assert st["objectives"][0]["reason"] == "You named the problem clearly."
    assert [c["score"] for c in st["competencies"]] == [1, 0]  # missing competency → 0, not invented
    assert st["checks"] == [] and len(st["progression"]) == 1
    sc = Scenario.objects.get(id=s.scenario_id)
    assert sc.facts == FACTS  # extracted once and cached on the scenario
    # Idempotent: posting again doesn't rescore (or charge) the same turn.
    from apps.providers.models import UsageCounter

    charged = UsageCounter.objects.get(user=s.user, metric=coach.METRIC).amount
    client.post(f"/api/roleplay/sessions/{s.id}/coach/")
    assert (
        UsageCounter.objects.get(user=s.user, metric=coach.METRIC).amount == charged == 2
    )  # facts + one turn
    _say(s, "Shall we look at the items together?")
    st = client.post(f"/api/roleplay/sessions/{s.id}/coach/").data
    assert (
        len(st["progression"]) == 2 and UsageCounter.objects.get(user=s.user, metric=coach.METRIC).amount == 3
    )  # facts not re-extracted
    learner = s.turns.filter(role="learner")
    assert all(t.coach for t in learner)
    # Final report carries the progression.
    res = client.post(f"/api/roleplay/sessions/{s.id}/end/").data["result"]
    assert len(res["coach"]["progression"]) == 2 and res["coach"]["hints_used"] == 0


def test_objective_once_met_stays_met(auth, monkeypatch):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    _say(s, "Let me check the bill.")
    client.post(f"/api/roleplay/sessions/{s.id}/coach/")
    from llm.prompts.roleplay import ItemScore, TurnTrack

    lower = TurnTrack(
        objectives=[ItemScore(score=0, reason="x"), ItemScore(score=1, reason="y")],
        competencies=[],
        contradictions=[],
    )
    monkeypatch.setattr(coach, "complete_json_sync", lambda *a, **k: lower)
    _say(s, "Okay.")
    st = client.post(f"/api/roleplay/sessions/{s.id}/coach/").data
    assert [o["score"] for o in st["objectives"]] == [2, 3]


def test_contradiction_flagged_only_for_clear_mismatch(auth):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    _say(s, "Your bill is ₹1,420, sir.")
    st = client.post(f"/api/roleplay/sessions/{s.id}/coach/").data
    # Fake model returned 4 candidates: the right number, a low-confidence one and a bad index are all dropped.
    assert [(c["said"], c["note"]) for c in st["checks"]] == [
        ("₹1,420", "Check: the bill was ₹1,240, not ₹1,420")
    ]
    assert st["checks"][0]["fact"] == FACTS[0]


def test_correct_value_is_never_flagged(auth):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    _say(s, "The total is ₹1,240 — refunds within 30 days.")
    assert (
        client.post(f"/api/roleplay/sessions/{s.id}/coach/").data["checks"] == []
    )  # 30 days only at 0.4 confidence


def test_verified_checks_unit():
    raw = [
        FactCheck(fact_index=0, learner_quote="1,240", correction="same", confidence=0.99),
        FactCheck(fact_index=0, learner_quote="about a thousand", correction="no digits", confidence=0.99),
        FactCheck(fact_index=0, learner_quote="₹2,000", correction="not said", confidence=0.99),
        FactCheck(
            fact_index=1,
            learner_quote="14 days",
            correction="Check: refunds are within 7 days",
            confidence=0.9,
        ),
    ]
    out = coach.verified_checks(raw, FACTS, "It was about a thousand, 1,240 maybe, refunds in 14 days")
    assert [c["note"] for c in out] == ["Check: refunds are within 7 days"]


def test_no_facts_no_checks(auth, monkeypatch):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    Scenario.objects.filter(id=s.scenario_id).update(facts=[])
    _say(s, "Your bill is ₹1,420, sir.")
    assert client.post(f"/api/roleplay/sessions/{s.id}/coach/").data["checks"] == []


def test_hints_are_limited_private_and_counted(auth):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    turns_before = s.turns.count()
    for n in (1, 2, 3):
        r = client.post(f"/api/roleplay/sessions/{s.id}/hint/")
        assert r.status_code == 200 and r.data["hints_used"] == n and r.data["hints_left"] == 3 - n
        assert r.data["hint"]["text"] == "Try asking what they need from you before giving the answer."
    r = client.post(f"/api/roleplay/sessions/{s.id}/hint/")
    assert r.status_code == 429 and r.data["code"] == "hint_limit"
    assert s.turns.count() == turns_before  # never part of the character's transcript
    detail = client.get(f"/api/roleplay/sessions/{s.id}/").data
    assert all("Try asking" not in t["text"] for t in detail["turns"]) and detail["coach"]["hints_used"] == 3
    _say(s, "Let me check.")
    _say(s, "Here's a fix.")
    res = client.post(f"/api/roleplay/sessions/{s.id}/end/").data["result"]
    assert res["coach"]["hints_used"] == 3
    assert client.post(f"/api/roleplay/sessions/{s.id}/hint/").data["code"] == "not_active"


def test_someone_elses_session_is_refused(auth):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    _say(s, "Hello")
    other = User.objects.create_user("o@example.com", "Other#2026pass")
    client.force_authenticate(other)
    assert client.get(f"/api/roleplay/sessions/{s.id}/coach/").status_code == 404
    assert client.post(f"/api/roleplay/sessions/{s.id}/coach/").status_code == 404
    assert client.post(f"/api/roleplay/sessions/{s.id}/hint/").status_code == 404
    s.refresh_from_db()
    assert s.hints == [] and not s.turns.filter(coach__isnull=False).exists()
    client.force_authenticate(None)
    client.credentials()
    assert client.post(f"/api/roleplay/sessions/{s.id}/hint/").status_code == 401


def test_feature_switch_blocks_coach(auth):
    client, _ = auth
    me = User.objects.get(email="kavya@example.com")
    s = _session(client, me)
    org = Organization.objects.create(
        name="Vidya School", slug="vidya", kind="school", features={"roleplay": False}
    )
    Membership.objects.create(org=org, user=me, role="learner")
    for url in (f"/api/roleplay/sessions/{s.id}/coach/", f"/api/roleplay/sessions/{s.id}/hint/"):
        r = client.post(url)
        assert r.status_code == 403 and r.data["code"] == "feature_off"


@override_settings(ROLEPLAY_COACH_DAILY=2)
def test_daily_cap(auth):
    client, _ = auth
    s = _session(client, User.objects.get(email="kavya@example.com"))
    _say(s, "First line")
    assert client.post(f"/api/roleplay/sessions/{s.id}/coach/").status_code == 200  # facts + turn = 2
    _say(s, "Second line")
    r = client.post(f"/api/roleplay/sessions/{s.id}/coach/")
    assert r.status_code == 429 and r.data["code"] == "ai_budget_exceeded"
    r = client.post(f"/api/roleplay/sessions/{s.id}/hint/")
    assert r.status_code == 429 and r.data["code"] == "ai_budget_exceeded"
    s.refresh_from_db()
    assert s.hints == []  # a refused hint isn't counted against the session
    assert client.get(f"/api/roleplay/sessions/{s.id}/coach/").status_code == 200  # reading state is free
