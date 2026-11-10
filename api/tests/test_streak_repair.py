"""Streak repair: break recording (on award and the lazy "virtual" break), the coin path, 402/409, the free revival
window, the 7-day expiry, badges, and that every PlayerStats change happens under the row lock."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.game.catalog import STREAK_REPAIR_PRICE
from apps.game.models import Notification, PlayerStats, UserBadge, XPEvent
from apps.game.services import _touch_streak, award, detect_break, repair_streak

TODAY = timezone.localdate


def _user(email="s@example.com"):
    return User.objects.create_user(email, "Streak#Test2026")


def _stats(u, **kw):
    s, _ = PlayerStats.objects.get_or_create(user=u)
    for k, v in kw.items():
        setattr(s, k, v)
    s.save()
    return s


@pytest.mark.django_db
def test_touch_streak_records_only_real_breaks():
    today = TODAY()
    s = PlayerStats(streak=6, best_streak=6, last_active=today - timedelta(days=4), freezes=0)
    assert "streak_broken" in _touch_streak(s, today)
    assert s.streak == 1 and s.last_streak == 6 and s.broken_at == today and s.revive_started_at
    s = PlayerStats(streak=1, last_active=today - timedelta(days=4), freezes=0)
    assert (
        "streak_broken" not in _touch_streak(s, today) and s.broken_at is None
    )  # a 1-day run isn't a streak


@pytest.mark.django_db
def test_virtual_break_shows_the_offer_before_any_activity(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    _stats(u, streak=9, best_streak=9, last_active=TODAY() - timedelta(days=3), freezes=0)
    st = client.get("/api/game/status/").data
    assert st["streak"] == 0
    assert st["repair"]["last_streak"] == 9 and st["repair"]["price"] == STREAK_REPAIR_PRICE
    assert st["repair"]["revive_progress"] == 0 and st["repair"]["revive_open"] and st["repair"]["coins_ok"]
    s = PlayerStats.objects.get(user=u)
    assert s.streak == 9 and s.last_streak == 9 and s.broken_at == TODAY()  # kept until the next activity
    # The next lesson starts a new run without recording a second break.
    award(u, "lesson_complete", ref="lesson:1")
    s.refresh_from_db()
    assert s.streak == 1 and s.last_streak == 9


@pytest.mark.django_db
def test_alive_streaks_have_no_offer(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    _stats(u, streak=4, last_active=TODAY() - timedelta(days=1))
    assert client.get("/api/game/status/").data["repair"] is None
    _stats(u, streak=4, last_active=TODAY() - timedelta(days=2), freezes=1)  # a freeze will bridge it
    assert client.get("/api/game/status/").data["repair"] is None
    assert PlayerStats.objects.get(user=u).streak == 4


@pytest.mark.django_db
def test_repair_with_coins_then_409(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    _stats(u, streak=8, best_streak=8, last_active=TODAY() - timedelta(days=5), freezes=0, coins=50)
    r = client.post("/api/game/streak/repair/", {"how": "coins"}, format="json")
    assert r.status_code == 402 and r.data["code"] == "not_enough_coins"
    _stats(u, coins=STREAK_REPAIR_PRICE + 20)
    r = client.post("/api/game/streak/repair/", {"how": "coins"}, format="json")
    assert r.status_code == 200 and r.data["repaired"]["streak"] == 8
    st = r.data["status"]
    badges = r.data["repaired"]["badges"]
    assert badges == ["streak_3", "streak_7"]
    assert st["streak"] == 8 and st["coins"] == 20 + 25 * len(badges) and st["repair"] is None
    s = PlayerStats.objects.get(user=u)
    assert s.last_active == TODAY() - timedelta(days=1)  # today's first lesson continues it
    assert XPEvent.objects.filter(user=u, kind="streak_repair", coins=-STREAK_REPAIR_PRICE).count() == 1
    assert Notification.objects.filter(user=u, kind="streak", title__contains="8-day").exists()
    assert client.post("/api/game/streak/repair/", {"how": "coins"}, format="json").status_code == 409
    award(u, "lesson_complete", ref="lesson:9")
    s.refresh_from_db()
    assert s.streak == 9 and s.best_streak == 9


@pytest.mark.django_db
def test_repair_after_activity_today_adds_today(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    _stats(u, streak=5, best_streak=5, last_active=TODAY() - timedelta(days=4), freezes=0, coins=1000)
    out = award(u, "activity_correct", ref="act:1")
    assert out["streak"] == 1
    r = client.post("/api/game/streak/repair/", {"how": "coins"}, format="json")
    assert r.data["repaired"]["streak"] == 6 and r.data["status"]["streak"] == 6
    assert set(UserBadge.objects.filter(user=u).values_list("code", flat=True)) >= {"streak_3"}


@pytest.mark.django_db
def test_bad_requests(auth):
    client, _ = auth
    assert client.post("/api/game/streak/repair/", {"how": "magic"}, format="json").status_code == 400
    r = client.post("/api/game/streak/repair/", {"how": "coins"}, format="json")
    assert r.status_code == 404 and r.data["code"] == "no_offer"


@pytest.mark.django_db
def test_revival_three_lessons_in_72_hours_repairs_automatically(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    _stats(u, streak=12, best_streak=12, last_active=TODAY() - timedelta(days=3), freezes=0)
    client.get("/api/game/status/")  # comes back: break noticed, window opens
    r = client.post("/api/game/streak/repair/", {"how": "revive"}, format="json")
    assert r.status_code == 400 and r.data == {"code": "revive_incomplete", "progress": 0, "goal": 3}
    assert "streak_repaired" not in award(u, "lesson_complete", ref="lesson:1")
    assert "streak_repaired" not in award(u, "today_complete", ref="today:x")
    assert client.get("/api/game/status/").data["repair"]["revive_progress"] == 2
    out = award(u, "lesson_complete", ref="lesson:2")
    assert out["streak_repaired"] == {"streak": 13, "how": "revive", "badges": ["streak_3", "streak_7"]}
    assert out["streak"] == 13
    s = PlayerStats.objects.get(user=u)
    assert s.streak == 13 and s.coins >= 0
    assert not XPEvent.objects.filter(user=u, kind="streak_repair").exclude(coins=0).exists()  # free
    assert client.post("/api/game/streak/repair/", {"how": "revive"}, format="json").status_code == 409


@pytest.mark.django_db
def test_revival_window_closes_after_72_hours():
    u = _user()
    _stats(u, streak=5, last_active=TODAY() - timedelta(days=3), freezes=0)
    detect_break(u)
    PlayerStats.objects.filter(user=u).update(revive_started_at=timezone.now() - timedelta(hours=73))
    for i in range(3):
        assert "streak_repaired" not in award(u, "lesson_complete", ref=f"lesson:{i}")
    from apps.game.services import RepairError

    with pytest.raises(RepairError) as e:
        repair_streak(u, "revive")
    assert e.value.code == "revive_incomplete"


@pytest.mark.django_db
def test_offer_expires_after_seven_days():
    u = _user()
    _stats(
        u,
        streak=5,
        last_streak=7,
        broken_at=TODAY() - timedelta(days=8),
        last_active=TODAY() - timedelta(days=9),
    )
    _stats(u, streak=0, coins=1000)
    from apps.game.api import _status
    from apps.game.services import RepairError

    assert _status(u)["repair"] is None
    with pytest.raises(RepairError) as e:
        repair_streak(u, "coins")
    assert e.value.status == 404
    PlayerStats.objects.filter(user=u).update(broken_at=TODAY() - timedelta(days=7))
    assert _status(u)["repair"]["expires_on"] == TODAY()  # last day still counts


@pytest.mark.django_db
def test_shop_switched_off_blocks_coins_only(auth):
    from apps.orgs.models import Membership, Organization

    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    org = Organization.objects.create(name="S", slug="s", features={"shop": False})
    Membership.objects.create(org=org, user=u, role="learner")
    _stats(u, streak=5, last_active=TODAY() - timedelta(days=3), freezes=0, coins=1000)
    assert client.get("/api/game/status/").data["repair"]["coins_ok"] is False
    assert client.post("/api/game/streak/repair/", {"how": "coins"}, format="json").status_code == 403
    assert client.post("/api/game/streak/repair/", {"how": "revive"}, format="json").data["code"] == (
        "revive_incomplete"
    )


@pytest.mark.django_db
def test_repair_takes_the_row_lock(monkeypatch):
    """Every PlayerStats write in repair_streak goes through select_for_update (Postgres runs this for real)."""
    from django.db.models.query import QuerySet

    u = _user()
    _stats(u, streak=5, last_active=TODAY() - timedelta(days=3), freezes=0, coins=1000)
    locked = []
    orig = QuerySet.select_for_update

    def spy(self, *a, **k):
        if self.model is PlayerStats:
            locked.append(True)
        return orig(self, *a, **k)

    monkeypatch.setattr(QuerySet, "select_for_update", spy)
    out = repair_streak(u, "coins")
    assert out["streak"] == 5 and locked
    assert PlayerStats.objects.get(user=u).coins == 1000 - STREAK_REPAIR_PRICE + 25  # + the streak_3 badge


@pytest.mark.django_db
def test_a_pause_added_after_the_break_was_noticed_keeps_the_streak():
    from apps.game.api import _status
    from apps.study.models import StudyPause

    u = _user()
    _stats(u, streak=6, best_streak=6, last_active=TODAY() - timedelta(days=5), freezes=0)
    st = _status(u)
    assert st["streak"] == 0 and st["repair"]["last_streak"] == 6
    StudyPause.objects.create(user=u, start=TODAY() - timedelta(days=4), end=TODAY() + timedelta(days=2))
    st = _status(u)
    assert st["streak"] == 6 and st["repair"] is None  # nothing to repair any more
    assert award(u, "lesson_complete", ref="lesson:p")["streak"] == 7
