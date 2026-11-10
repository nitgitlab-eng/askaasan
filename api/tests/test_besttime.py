"""Learned best time: the 5-active-day threshold, the median of each day's first activity, the 21-day window, clearing a
stale estimate, nudge clamps (08:00-21:30), chosen vs learned study reminder time, `time_chosen` from the preferences
PATCH and from the data migration, and the learned time in the push status."""

import importlib
from datetime import datetime, time, timedelta

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.accounts import besttime
from apps.accounts.models import ReminderState, User
from apps.accounts.preferences import upgrade
from apps.game.models import XPEvent


def _user(email="b@example.com"):
    return User.objects.create_user(email, "Best#Time2026pw")


def _at(day, hh, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


def _activity(user, when, ref):
    e = XPEvent.objects.create(
        user=user, kind="lesson_complete", ref=ref, xp=10, day=timezone.localdate(when)
    )
    XPEvent.objects.filter(pk=e.pk).update(created_at=when)


def test_helpers():
    assert besttime.hhmm(450) == "07:30" and besttime.parse("07:30") == 450
    assert besttime.parse("25:00") is None and besttime.parse("x") is None and besttime.parse(None) is None
    assert besttime.round_down_15(18 * 60 + 44) == 18 * 60 + 30
    assert besttime.learned_minute([1, 2, 3, 4]) is None and besttime.learned_minute([1, 2, 3, 4, 50]) == 3


@pytest.mark.django_db
def test_median_of_first_activity_needs_five_days():
    today = timezone.localdate()
    u, few, old = _user(), _user("few@example.com"), _user("old@example.com")
    for i, (hh, mm) in enumerate([(7, 10), (7, 20), (7, 30), (20, 0), (7, 40)], start=1):
        day = today - timedelta(days=i)
        _activity(u, _at(day, hh, mm), f"a{i}")
        _activity(u, _at(day, 22, 0), f"late{i}")  # later the same day: only the first counts
    for i in range(1, 5):
        _activity(few, _at(today - timedelta(days=i), 9), f"f{i}")
    for i in range(22, 30):
        _activity(old, _at(today - timedelta(days=i), 9), f"o{i}")  # outside the 21-day window
    ReminderState.objects.create(user=old, best_minute=600, best_days=6)
    out = besttime.compute_all()
    assert out == {"learned": 1, "users": 2, "cleared": 1}
    st = ReminderState.objects.get(user=u)
    assert (st.best_minute, st.best_days) == (7 * 60 + 30, 5) and st.best_computed_at
    assert ReminderState.objects.get(user=few).best_minute is None
    assert ReminderState.objects.get(user=old).best_minute is None  # a stale estimate is cleared
    # Idempotent and updates in place.
    besttime.compute_all()
    assert ReminderState.objects.filter(user=u).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("best", "times", "nudge"),
    [
        (None, ["19:00"], 18 * 60 + 30),  # nothing learned, default time
        (7 * 60 + 30, ["19:00"], 8 * 60),  # early bird: never before 08:00
        (23 * 60 + 30, ["19:00"], 21 * 60 + 30),  # night owl: never after 21:30
        (14 * 60, ["06:00"], 13 * 60 + 30),  # learned beats the reminder time
        (None, ["10:15"], 9 * 60 + 45),  # no estimate: the learner's first reminder time
        (None, [], 18 * 60 + 30),
    ],
)
def test_nudge_minute(best, times, nudge):
    u = _user()
    st = ReminderState.objects.create(user=u, best_minute=best)
    prefs = upgrade(u.preferences.data)
    prefs["learning"]["reminder_times"] = times
    assert besttime.nudge_minute(u, prefs, st) == nudge


@pytest.mark.django_db
def test_study_reminder_time_chosen_vs_learned():
    u = _user()
    st = ReminderState.objects.create(user=u, best_minute=10 * 60 + 10)
    prefs = upgrade(u.preferences.data)
    assert besttime.study_times(u, prefs, st) == {"09:30"}  # 09:40 rounded down to the 15-minute beat
    st.time_chosen = True
    prefs["learning"]["reminder_times"] = ["23:00"]
    assert besttime.study_times(u, prefs, st) == {"23:00"}  # the learner chose it, even late at night
    st.time_chosen = False
    assert besttime.study_times(u, prefs, st) == {"23:00"}  # a non-default value was chosen too


@pytest.mark.django_db
def test_patch_with_reminder_times_marks_the_time_chosen(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    client.patch("/api/users/preferences/", {"learning": {"daily_goal_minutes": 20}}, format="json")
    assert not ReminderState.objects.filter(user=u, time_chosen=True).exists()
    r = client.patch("/api/users/preferences/", {"learning": {"reminder_times": ["19:00"]}}, format="json")
    assert r.status_code == 200 and ReminderState.objects.get(user=u).time_chosen
    assert client.get("/api/users/push/").data["reminders"]["time_chosen"] is True


@pytest.mark.django_db
def test_migration_marks_stored_non_default_times():
    mod = importlib.import_module("apps.accounts.migrations.0012_reminders")
    picked, default, empty = _user(), _user("d@example.com"), _user("e@example.com")
    for user, times in ((picked, ["07:00", "20:00"]), (default, ["19:00"]), (empty, [])):
        p = user.preferences
        p.data = {**p.data, "learning": {**p.data["learning"], "reminder_times": times}}
        p.save()
    mod.mark_chosen_times(django_apps, None)
    assert list(ReminderState.objects.filter(time_chosen=True).values_list("user_id", flat=True)) == [
        picked.id
    ]
    mod.mark_chosen_times(django_apps, None)  # rerun-safe
    assert ReminderState.objects.filter(user=picked).count() == 1


@pytest.mark.django_db
def test_learned_time_in_push_status(auth):
    client, _ = auth
    u = User.objects.get(email="kavya@example.com")
    ReminderState.objects.create(user=u, best_minute=7 * 60 + 5, best_days=6)
    rem = client.get("/api/users/push/").data["reminders"]
    assert rem == {"state": "normal", "since": None, "learned_time": "07:05", "time_chosen": False}
