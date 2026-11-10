"""Step-up after a miss: day 1 (D+2) and day 2 (D+3) streak nudges with the repair offer, reruns, every skip, the
win-back day-3 handover, the no-streak missed-day nudge, and the study reminder leaving its push to step-up.
pywebpush is replaced; nothing reaches a push service."""

import base64
import json
import os
from datetime import datetime, time, timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts import push, stepup, winback
from apps.accounts.models import PushLog, ReminderState, User, WinbackSend
from apps.game.models import Notification, PlayerStats, XPEvent

P256 = base64.urlsafe_b64encode(b"\x04" + os.urandom(64)).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")
T = timezone.localdate()


def at(day, hh=19, mm=0):
    return timezone.make_aware(datetime.combine(day, time(hh, mm)))


@pytest.fixture
def sent(monkeypatch, settings):
    settings.WEBPUSH_ENABLED = True
    settings.WEBPUSH_VAPID_PUBLIC_KEY = "BPublicKeyForTests"
    settings.WEBPUSH_VAPID_PRIVATE_KEY = "private-key-for-tests"
    import pywebpush

    calls = []
    monkeypatch.setattr(
        pywebpush, "webpush", lambda subscription_info, data, **kw: calls.append(json.loads(data))
    )
    return calls


def learner(email="s@example.com", gap=2, streak=5, device=True, **kw):
    u = User.objects.create_user(email, "Step#Up2026pw", email_verified=True)
    PlayerStats.objects.create(user=u, last_active=T - timedelta(days=gap), streak=streak, freezes=0, **kw)
    if device:
        push.subscribe(u, f"https://fcm.googleapis.com/fcm/send/{email}", P256, AUTH)
    return u


@pytest.mark.django_db
def test_day_one_and_day_two_after_the_miss(sent):
    u = learner()
    assert stepup.run(at(T)) == {"streak_lost_1": 1, "streak_lost_2": 0, "missed_day": 0}
    s = PlayerStats.objects.get(user=u)
    assert s.broken_at == T and s.last_streak == 5 and s.revive_started_at  # the real repair window is open
    assert WinbackSend.objects.get(user=u).kind == "stepup_1"
    assert sent[-1]["url"] == "/achievements?repair=1" and "5" in sent[-1]["title"] + sent[-1]["body"]
    bell = Notification.objects.get(user=u, kind="stepup")
    assert (bell.title, bell.link) == (sent[-1]["title"], "/achievements?repair=1")
    assert PushLog.objects.get(token=sent[-1]["id"]).moment == "streak_lost_1"
    assert stepup.run(at(T, 20)) == {"streak_lost_1": 0, "streak_lost_2": 0, "missed_day": 0}  # rerun
    # The next day: the last call, with the hours left in the free revival window.
    out = stepup.run(at(T + timedelta(days=1)))
    assert out["streak_lost_2"] == 1 and len(sent) == 2
    assert "48" in sent[-1]["title"] + sent[-1]["body"]
    assert stepup.run(at(T + timedelta(days=1), 21))["streak_lost_2"] == 0
    assert set(WinbackSend.objects.filter(user=u).values_list("kind", "episode")) == {
        ("stepup_1", T),
        ("stepup_2", T),
    }
    # Day 3 of the break: step-up is done.
    assert sum(stepup.run(at(T + timedelta(days=2))).values()) == 0


@pytest.mark.django_db
def test_acts_at_the_nudge_time_in_the_daytime_only(sent):
    u = learner()
    assert sum(stepup.run(at(T, 12)).values()) == 0  # default nudge 18:30
    assert sum(stepup.run(at(T, 23)).values()) == 0
    ReminderState.objects.create(user=u, best_minute=11 * 60)
    assert stepup.run(at(T, 10, 45))["streak_lost_1"] == 1


@pytest.mark.django_db
def test_skips(sent, monkeypatch, settings):
    learner("nodevice@example.com", device=False)
    learner("recent@example.com", gap=1)
    learner("old@example.com", gap=5)
    used = learner("used@example.com")
    PlayerStats.objects.filter(user=used).update(last_streak=5, broken_at=T)
    XPEvent.objects.create(user=used, kind="streak_repair", ref=f"repair:{T.isoformat()}", day=T)
    paused = learner("paused@example.com")
    ReminderState.objects.create(user=paused, backoff="paused", backoff_since=timezone.now())
    away = learner("away@example.com")
    monkeypatch.setattr("apps.study.planner.paused_on", lambda uid, d: uid == away.id)
    inactive = learner("inactive@example.com")
    User.objects.filter(pk=inactive.pk).update(is_active=False)
    assert sum(stepup.run(at(T)).values()) == 0 and not sent
    assert not WinbackSend.objects.exists()  # nothing claimed, so a later run can still send
    ok = learner("ok@example.com")
    settings.WEBPUSH_ENABLED = False
    assert sum(stepup.run(at(T)).values()) == 0
    settings.WEBPUSH_ENABLED = True
    assert stepup.run(at(T))["streak_lost_1"] == 1 and WinbackSend.objects.get().user == ok


@pytest.mark.django_db
def test_winback_day_three_hands_push_and_bell_to_stepup(sent):
    u = learner(gap=3)  # last studied T-3: step-up day 1 was T-1, day 2 is T, win-back day 3 is T
    assert stepup.run(at(T - timedelta(days=1)))["streak_lost_1"] == 1
    out = winback.inactive(at(T, 10, 30))  # the win-back runs in the morning
    assert out["inactive_3"] == 1 and len(mail.outbox) == 1  # the email always goes
    assert not Notification.objects.filter(user=u, kind="winback").exists()
    assert len(sent) == 1  # no win-back push: the repair offer is open, step-up owns it
    assert (
        stepup.run(at(T))["streak_lost_2"] == 1
    )  # and the step-up's own claims don't count as win-back quiet
    # A learner without a streak gets the full win-back.
    plain = learner("plain@example.com", gap=3, streak=0)
    winback.inactive(at(T, 10, 30))
    assert Notification.objects.filter(user=plain, kind="winback").exists()
    assert any(p["kind"] == "winback" for p in sent)


@pytest.mark.django_db
def test_winback_day_three_yields_after_stepup_two_even_without_an_offer(sent):
    u = learner(gap=3)
    WinbackSend.objects.create(user=u, kind="stepup_2", episode=T - timedelta(days=3))
    winback.inactive(at(T, 10, 30))
    assert len(mail.outbox) == 1 and not Notification.objects.filter(user=u, kind="winback").exists()
    assert not sent


@pytest.mark.django_db
def test_missed_day_for_learners_without_a_streak(sent):
    u = learner(streak=1)
    out = stepup.run(at(T))
    assert out == {"streak_lost_1": 0, "streak_lost_2": 0, "missed_day": 1}
    assert sent[-1]["url"] == "/today" and sent[-1]["kind"] == "study"
    assert WinbackSend.objects.get(user=u).episode == T - timedelta(days=2)
    assert sum(stepup.run(at(T, 21)).values()) == 0
    assert sum(stepup.run(at(T + timedelta(days=1))).values()) == 0  # once per lapse
    # Yesterday wasn't one of their study days: nothing to nudge about.
    rest = learner("rest@example.com", streak=0)
    p = rest.preferences
    yesterday = (T - timedelta(days=1)).weekday()
    p.data = {
        **p.data,
        "learning": {**p.data["learning"], "study_days": [d for d in range(7) if d != yesterday]},
    }
    p.save()
    assert stepup.run(at(T))["missed_day"] == 0


@pytest.mark.django_db
def test_supersedes_study():
    u = User.objects.create_user("sup@example.com", "Step#Up2026pw")

    def stats(gap, streak, freezes=0):
        return PlayerStats(user=u, last_active=T - timedelta(days=gap), streak=streak, freezes=freezes)

    assert stepup.supersedes_study(u, stats(1, 5), T)  # streak at risk tonight
    assert not stepup.supersedes_study(u, stats(1, 1), T)
    assert stepup.supersedes_study(u, stats(2, 5), T)  # step-up day 1
    assert not stepup.supersedes_study(u, stats(2, 5, freezes=1), T)  # a freeze still bridges it
    assert stepup.supersedes_study(u, stats(2, 0), T)  # missed day
    assert not stepup.supersedes_study(u, stats(4, 5), T)
    assert not stepup.supersedes_study(u, None, T)


@pytest.mark.django_db
def test_study_reminder_leaves_its_push_to_the_streak_nudge(sent):
    from apps.accounts.study_reminders import send_due

    u = learner(gap=1)
    ReminderState.objects.create(user=u, time_chosen=True)
    assert send_due(at(T, 19, 5)) == 1
    assert Notification.objects.filter(user=u, kind="study_reminder").exists() and len(mail.outbox) == 1
    assert not sent  # the evening streak-risk push speaks for today
