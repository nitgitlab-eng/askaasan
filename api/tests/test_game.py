from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.game.catalog import level_for
from apps.game.models import Notification, PlayerStats, XPEvent
from apps.game.services import _touch_streak, award, nudges, pay_referral

pytestmark = pytest.mark.django_db


def me():
    return User.objects.get(email="kavya@example.com")


def test_level_curve():
    assert [level_for(x) for x in (0, 49, 50, 199, 200, 800, 4050)] == [1, 1, 2, 2, 3, 5, 10]


def test_award_is_idempotent_and_levels_up(auth):
    u = me()
    first = award(u, "lesson_complete", ref="lesson:1")
    assert first["xp"] == 50 and first["level_up"] == 2
    assert award(u, "lesson_complete", ref="lesson:1")["duplicate"] is True
    s = PlayerStats.objects.get(user=u)
    assert s.xp == 50 and s.coins == 10 and s.streak == 1
    assert Notification.objects.filter(user=u, kind="level_up").exists()


def test_streak_rules():
    today = timezone.localdate()
    s = PlayerStats(streak=4, best_streak=4, last_active=today - timedelta(days=1), freezes=1)
    _touch_streak(s, today)
    assert s.streak == 5
    s = PlayerStats(streak=4, best_streak=4, last_active=today - timedelta(days=2), freezes=1)
    assert "freeze_used" in _touch_streak(s, today) and s.streak == 5 and s.freezes == 0
    s = PlayerStats(streak=4, best_streak=9, last_active=today - timedelta(days=2), freezes=0)
    assert "streak_broken" in _touch_streak(s, today)
    assert s.streak == 1 and s.best_streak == 9
    # The lost streak is kept for a repair (see test_streak_repair.py).
    assert s.last_streak == 4 and s.broken_at == today and s.revive_started_at is not None


def test_streak_badges_and_daily_goal(auth):
    u = me()
    PlayerStats.objects.create(
        user=u, streak=2, best_streak=2, last_active=timezone.localdate() - timedelta(days=1)
    )
    out = award(u, "activity_correct", ref="a1", xp=200)  # crosses default 60-XP daily goal
    assert "streak_3" in out["badges"] and out["daily_goal"] is True
    assert XPEvent.objects.filter(user=u, kind="daily_goal").count() == 1
    award(u, "activity_correct", ref="a2", xp=10)
    assert XPEvent.objects.filter(user=u, kind="daily_goal").count() == 1  # once per day


def test_lesson_flow_rewards(auth):
    client, _ = auth
    cid = client.post("/api/learn/curriculums/", {"goal": "AI basics"}, format="json").data["id"]
    sub = client.get(f"/api/learn/curriculums/{cid}/").data["sections"][0]["subsections"][0]["id"]
    lesson = client.post(f"/api/learn/subsections/{sub}/start/").data
    quiz = next(a for a in lesson["activities"] if a["type"] == "quiz")
    r = client.post(
        f"/api/learn/activities/{quiz['id']}/attempt/", {"answer": {"selected": [1]}}, format="json"
    ).data
    assert r["reward"]["xp"] == 15  # 10 + first-try perfect bonus
    again = client.post(
        f"/api/learn/activities/{quiz['id']}/attempt/", {"answer": {"selected": [1]}}, format="json"
    ).data
    assert again["reward"]["xp"] == 0  # no farming
    recap = client.post(f"/api/learn/subsections/{sub}/complete/").data
    assert recap["reward"]["xp"] >= 50 and "first_lesson" in recap["reward"]["badges"]
    st = client.get("/api/game/status/").data
    assert st["xp"] >= 65 and st["streak"] == 1 and st["active_today"] and st["unread"] >= 1


def test_shop_buy_and_equip(auth):
    client, _ = auth
    assert (
        client.patch("/api/users/preferences/", {"mascot": {"outfit": "veshti"}}, format="json").status_code
        == 403
    )
    assert client.post("/api/game/shop/buy/", {"item": "veshti"}, format="json").status_code == 402
    s = PlayerStats.objects.get_or_create(user=me())[0]
    s.coins = 500
    s.save()
    assert (
        client.post("/api/game/shop/buy/", {"item": "crown"}, format="json").status_code == 403
    )  # level locked
    res = client.post("/api/game/shop/buy/", {"item": "veshti"}, format="json")
    assert res.status_code == 200 and "veshti" in res.data["owned_items"] and res.data["coins"] == 380
    assert client.post("/api/game/shop/buy/", {"item": "veshti"}, format="json").status_code == 400
    assert (
        client.patch("/api/users/preferences/", {"mascot": {"outfit": "veshti"}}, format="json").status_code
        == 200
    )
    assert client.post("/api/game/shop/buy/", {"item": "streak_freeze"}, format="json").data["freezes"] == 2
    assert (
        client.post("/api/game/shop/buy/", {"item": "streak_freeze"}, format="json").status_code == 400
    )  # max 2


def test_leaderboard_privacy(auth):
    client, _ = auth
    u = me()
    u.profile.display_name = "Kavya Ramesh"
    u.profile.save()
    other = User.objects.create_user("o@example.com", "Other#2026pass")
    other.profile.display_name = "Arun Kumar"
    other.profile.save()
    award(u, "activity_correct", ref="x", xp=100)
    award(other, "activity_correct", ref="y", xp=300)
    rows = client.get("/api/game/leaderboard/").data["rows"]
    assert [r["name"] for r in rows] == ["Arun", "Kavya"]  # first names only
    assert rows[0]["league"]["name"] == "silver" and rows[1]["me"] is True
    PlayerStats.objects.filter(user=other).update(show_on_leaderboard=False)
    assert [r["name"] for r in client.get("/api/game/leaderboard/").data["rows"]] == ["Kavya"]


def test_boss_battle_server_verdict(auth):
    client, _ = auth
    cid = client.post("/api/learn/curriculums/", {"goal": "AI basics"}, format="json").data["id"]
    d = client.get(f"/api/learn/curriculums/{cid}/").data
    sec = d["sections"][0]["id"]
    client.post(f"/api/learn/subsections/{d['sections'][0]['subsections'][0]['id']}/start/")
    assert client.post(f"/api/game/boss/{sec}/result/").status_code == 400  # no answers yet
    from apps.learning.models import Activity

    cards = client.get(f"/api/review/session/?mode=section&section={sec}").data["cards"]
    for c in cards:
        key = Activity.objects.get(id=c["activity"]["id"]).key
        ans = (
            {"selected": key.get("correct")}
            if "correct" in key
            else {"order": key.get("order")}
            if "order" in key
            else {"assign": key.get("assign")}
            if "assign" in key
            else {"pairs": key.get("pairs")}
            if "pairs" in key
            else {"blanks": {b: v[0] for b, v in key.get("blanks", {}).items()}}
        )
        client.post(f"/api/review/cards/{c['card_id']}/answer/", {"answer": ans}, format="json")
    r = client.post(f"/api/game/boss/{sec}/result/").data
    assert r["won"] is True and r["reward"]["xp"] >= 120 and "boss_slayer" in r["reward"]["badges"]
    assert client.post(f"/api/game/boss/{sec}/result/").data["reward"]["duplicate"] is True


def test_referral_rewards_both(client, db):
    inviter = User.objects.create_user("inv@example.com", "Inviter#2026pass")
    code = PlayerStats.objects.get_or_create(user=inviter)[0].referral_code
    res = client.post(
        "/api/users/register/",
        {"email": "new@example.com", "password": "Newbie#2026pass", "ref": code},
        format="json",
    )
    assert res.status_code == 201
    new = User.objects.get(email="new@example.com")
    assert (
        PlayerStats.objects.get(user=inviter).coins == 0
    )  # nothing until the new account verifies its email
    new.email_verified = True
    new.save(update_fields=["email_verified"])
    assert pay_referral(new) is True
    assert PlayerStats.objects.get(user=inviter).coins >= 100
    assert PlayerStats.objects.get(user=new).coins == 100
    assert inviter.badges.filter(code="friend").exists()
    assert pay_referral(new) is False  # paid once


def test_nudges_and_plan(auth):
    client, _ = auth
    assert nudges(me()) == []
    plan = client.get("/api/game/plan/").data
    assert len(plan["days"]) == 7 and plan["goal_minutes"] == 15
    ics = client.get("/api/game/plan.ics")
    body = ics.content.decode()
    assert (
        ics["Content-Type"].startswith("text/calendar") and "UID:aasan-block-" in body
    )  # concrete planner blocks (Milestone 3)


def test_plan_does_not_mark_days_before_first_activity_missed(auth):
    client, _ = auth
    award(me(), "activity_correct", ref="today", xp=10)
    days = client.get("/api/game/plan/").data["days"]
    today = timezone.localdate()
    assert all(d["state"] != "missed" for d in days if d["day"] < today)
