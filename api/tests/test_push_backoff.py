"""Back off when ignored: the payload token and PushLog, the opened endpoint (public, always 204, validated, recent
only, throttled), alternate / paused thresholds, the one notice, kinds that are never gated, every way back to normal
(open, app visit, activity, Resume), the daily cap, pruning and the status shape. pywebpush is replaced."""

import base64
import json
import os
import re
import secrets
from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts import cadence, push
from apps.accounts.models import PushLog, ReminderState, User
from apps.game.models import Notification

P256 = base64.urlsafe_b64encode(b"\x04" + os.urandom(64)).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")
T = timezone.localdate()


def at(day, hh=12, mm=0):
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


def _user(email="bo@example.com", device=True):
    u = User.objects.create_user(email, "Back#Off2026pw")
    if device:
        push.subscribe(u, f"https://fcm.googleapis.com/fcm/send/{email}", P256, AUTH)
    return u


def _logs(user, n, kind="study", when=None, **kw):
    when = when or timezone.now() - timedelta(days=1)
    return [
        PushLog.objects.create(
            user=user, token=secrets.token_urlsafe(16), kind=kind, sent_at=when - timedelta(minutes=i), **kw
        )
        for i in range(n)
    ]


def _state(user):
    return ReminderState.objects.get(user=user).backoff


@pytest.mark.django_db
def test_every_push_is_logged_with_a_token_in_the_payload(sent):
    u = _user()
    assert push.send(u, "teacher", "Hi", "From your teacher", "/learn")
    assert push.send(
        u, "streak", "🔥", "Keep it", "/today", moment="streak_risk", variant="streak_risk.anna_akka.0"
    )
    log = PushLog.objects.get(token=sent[-1]["id"])
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,32}", log.token)
    assert (log.kind, log.moment, log.variant, log.opened_at) == (
        "streak",
        "streak_risk",
        "streak_risk.anna_akka.0",
        None,
    )
    assert PushLog.objects.filter(user=u).count() == 2 and sent[0]["id"] != sent[1]["id"]


@pytest.mark.django_db
def test_opened_endpoint(sent):
    u = _user()
    push.send(u, "study", "x")
    token = sent[-1]["id"]
    c = APIClient()  # the service worker has no session
    for bad in (
        {},
        {"id": 5},
        {"id": "short"},
        {"id": "x" * 40},
        {"id": "bad token with spaces!"},
        {"id": "a" * 22},
    ):
        assert c.post("/api/users/push/opened/", bad, format="json").status_code == 204
    assert not PushLog.objects.filter(opened_at__isnull=False).exists()
    assert c.post("/api/users/push/opened/", {"id": token}, format="json").status_code == 204
    log = PushLog.objects.get(token=token)
    assert log.opened_at and log.opened_via == "push"
    first = log.opened_at
    assert c.post("/api/users/push/opened/", {"id": token}, format="json").status_code == 204
    assert PushLog.objects.get(token=token).opened_at == first  # only the first tap counts
    assert c.get("/api/users/push/opened/").status_code == 405
    # Older than 7 days: ignored.
    (old,) = _logs(u, 1, when=timezone.now() - timedelta(days=8))
    c.post("/api/users/push/opened/", {"id": old.token}, format="json")
    assert PushLog.objects.get(pk=old.pk).opened_at is None


@pytest.mark.django_db
def test_opened_endpoint_is_throttled_per_ip():
    c = APIClient()
    codes = [
        c.post("/api/users/push/opened/", {"id": "a" * 22}, format="json").status_code for _ in range(61)
    ]
    assert codes[:60] == [204] * 60 and codes[60] == 429


@pytest.mark.django_db
def test_thresholds_alternate_then_paused():
    from apps.game.models import XPEvent

    u = _user(device=False)
    _logs(u, 6, when=timezone.now() - timedelta(days=3))
    e = XPEvent.objects.create(user=u, kind="lesson_complete", ref="x", xp=10, day=T)
    XPEvent.objects.filter(pk=e.pk).update(created_at=timezone.now() - timedelta(days=2))
    _logs(u, 4)  # after the last activity
    _logs(u, 3, kind="teacher")  # never counted
    _logs(u, 2, moment="backoff_notice")  # nor the notice itself
    assert cadence.ignored_count(u.id) == 4 and cadence.evaluate(u.id) == "normal"
    _logs(u, 1)
    assert cadence.evaluate(u.id) == "alternate" and ReminderState.objects.get(user=u).backoff_since
    _logs(u, 3)
    assert cadence.evaluate_all() == {"normal": 0, "alternate": 0, "paused": 1}
    assert _state(u) == "paused"


@pytest.mark.django_db
def test_an_open_restarts_the_count():
    u = _user(device=False)
    logs = _logs(u, 7)
    PushLog.objects.filter(pk=logs[0].pk).update(opened_at=timezone.now() - timedelta(hours=1))
    assert cadence.ignored_count(u.id) == 0
    assert cadence.target_state(4) == "normal" and cadence.target_state(5) == "alternate"
    assert cadence.target_state(8) == "paused"


@pytest.mark.django_db
def test_alternate_days_and_paused_gate(sent):
    u = _user()
    since = at(T - timedelta(days=10), 9)
    ReminderState.objects.create(user=u, backoff="alternate", backoff_since=since)
    assert cadence.allowed(u, "study", now=at(T - timedelta(days=10)))  # day 0
    assert not cadence.allowed(u, "study", now=at(T - timedelta(days=9)))  # day 1
    assert cadence.allowed(u, "reviews", now=at(T - timedelta(days=8)))  # day 2
    ReminderState.objects.filter(user=u).update(backoff="paused")
    for kind in ("study", "streak", "reviews"):
        assert not cadence.allowed(u, kind)
    assert cadence.allowed(u, "winback")
    assert push.send(u, "study", "x") is False and push.send(u, "winback", "x") is True


@pytest.mark.django_db
def test_kinds_that_are_never_gated(sent):
    u = _user()
    ReminderState.objects.create(user=u, backoff="paused", backoff_since=timezone.now())
    _logs(u, 5, when=timezone.now())  # over the daily cap too
    for kind in ("teacher", "workshops", "plan", "test"):
        assert push.send(u, kind, "x"), kind


@pytest.mark.django_db
def test_daily_cap(sent):
    u = _user()
    assert push.send(u, "study", "a") and push.send(u, "streak", "b")
    assert push.send(u, "reviews", "c") is False  # two reminder pushes a day at most
    assert push.send(u, "study", "x", moment="backoff_notice")  # the notice is not a reminder
    PushLog.objects.update(sent_at=timezone.now() - timedelta(days=1))
    assert push.send(u, "reviews", "c")


@pytest.mark.django_db
def test_one_notice_when_first_paused_in_the_daytime(sent):
    u = _user()
    ReminderState.objects.create(user=u, backoff="paused", backoff_since=timezone.now())
    assert cadence.send_notices(at(T, 3, 15)) == 0  # not at night
    assert cadence.send_notices(at(T, 10)) == 1
    assert sent[-1]["url"] == "/account#push"
    assert PushLog.objects.get(token=sent[-1]["id"]).moment == "backoff_notice"
    bell = Notification.objects.get(user=u, kind="reminders")
    assert bell.link == "/account#push" and bell.title == sent[-1]["title"]
    assert cadence.send_notices(at(T, 11)) == 0 and len(sent) == 1
    assert ReminderState.objects.get(user=u).notice_sent_at


@pytest.mark.django_db
def test_ways_back_to_normal(sent, auth):
    from apps.accounts.tokens import touch_last_seen
    from apps.game.services import award

    u = _user()
    st = ReminderState.objects.create(
        user=u, backoff="paused", backoff_since=timezone.now(), notice_sent_at=timezone.now()
    )
    # 1. Any activity.
    award(u, "lesson_complete", ref="back")
    st.refresh_from_db()
    assert (st.backoff, st.backoff_since, st.notice_sent_at) == ("normal", None, None)
    # 2. Tapping a notification.
    ReminderState.objects.filter(user=u).update(backoff="alternate", backoff_since=timezone.now())
    push.send(u, "winback", "x")
    APIClient().post("/api/users/push/opened/", {"id": sent[-1]["id"]}, format="json")
    assert _state(u) == "normal"
    # 3. Opening the app within 6 hours of a push (the token refresh records the visit).
    ReminderState.objects.filter(user=u).update(backoff="paused", backoff_since=timezone.now())
    (recent,) = _logs(u, 1, when=timezone.now() - timedelta(hours=2))
    (old,) = _logs(u, 1, when=timezone.now() - timedelta(hours=8))
    touch_last_seen(u)
    assert PushLog.objects.get(pk=recent.pk).opened_via == "app"
    assert PushLog.objects.get(pk=old.pk).opened_at is None
    assert _state(u) == "normal"
    # 4. The Resume button: counting starts again from there, so the nightly run doesn't pause them straight away.
    client, _ = auth
    k = User.objects.get(email="kavya@example.com")
    _logs(k, 9)
    assert cadence.evaluate(k.id) == "paused"
    st = client.get("/api/users/push/").data["reminders"]
    assert st["state"] == "paused" and st["since"]
    r = client.post("/api/users/push/reminders/resume/")
    assert r.status_code == 200 and r.data["reminders"]["state"] == "normal"
    assert cadence.evaluate(k.id) == "normal"
    assert APIClient().post("/api/users/push/reminders/resume/").status_code == 401


@pytest.mark.django_db
def test_nightly_prunes_old_logs_and_runs_everything(sent):
    from apps.accounts import tasks

    u = _user()
    _logs(u, 2, when=timezone.now() - timedelta(days=91))
    _logs(u, 1)
    out = tasks.reminder_nightly()
    assert out["pruned"] == 2 and PushLog.objects.filter(user=u).count() == 1
    assert set(out) == {"best", "backoff", "pruned"}
    assert set(tasks.stepup_checks()) == {"stepup", "notices"}


@pytest.mark.django_db
def test_send_still_never_raises_and_drops_the_log_when_queueing_fails(sent, monkeypatch):
    from apps.accounts import tasks

    u = _user()

    def boom(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.push_deliver, "delay", boom)
    assert push.send(u, "study", "x") is False and not PushLog.objects.exists()
    monkeypatch.setattr(cadence, "allowed", boom)
    assert push.send(u, "study", "x") is False
