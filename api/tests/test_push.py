"""Web push: subscription validation (SSRF allowlist, keys, cap), preferences, delivery failure handling, the four
reminder hooks and the evening check. pywebpush's transport is always replaced; nothing reaches a push service."""

import base64
import os
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from apps.accounts import push
from apps.accounts.models import PushLog, PushSubscription, ReminderState, User

P256 = base64.urlsafe_b64encode(b"\x04" + os.urandom(64)).decode().rstrip("=")
AUTH = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")
FCM = "https://fcm.googleapis.com/fcm/send/abc123"


def sub_body(endpoint=FCM, p256dh=P256, auth=AUTH):
    return {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}


@pytest.fixture
def vapid(settings):
    settings.WEBPUSH_ENABLED = True
    settings.WEBPUSH_VAPID_PUBLIC_KEY = "BPublicKeyForTests"
    settings.WEBPUSH_VAPID_PRIVATE_KEY = "private-key-for-tests"
    settings.WEBPUSH_VAPID_SUBJECT = "mailto:test@example.com"


class FakeResponse:
    def __init__(self, code):
        self.status_code = code


@pytest.fixture
def sent(monkeypatch, vapid):
    """Replace pywebpush.webpush; `outcome[endpoint]` = an HTTP status to fail with, or an exception to raise."""
    import pywebpush

    calls, outcome = [], {}

    def fake(subscription_info, data, vapid_private_key, vapid_claims, ttl, timeout):
        assert vapid_private_key == "private-key-for-tests" and ttl == 3600
        calls.append({"endpoint": subscription_info["endpoint"], "data": data, "claims": vapid_claims})
        res = outcome.get(subscription_info["endpoint"])
        if isinstance(res, int):
            raise pywebpush.WebPushException("push failed", response=FakeResponse(res))
        if isinstance(res, Exception):
            raise res

    monkeypatch.setattr(pywebpush, "webpush", fake)
    return calls, outcome


def _user(email="p@example.com"):
    return User.objects.create_user(email, "Push#Test2026pw")


@pytest.mark.django_db
def test_status_off_without_keys(auth, settings):
    settings.WEBPUSH_VAPID_PUBLIC_KEY = settings.WEBPUSH_VAPID_PRIVATE_KEY = ""
    client, _ = auth
    r = client.get("/api/users/push/")
    assert r.status_code == 200 and r.data == {
        "enabled": False,
        "public_key": "",
        "subscribed": False,
        "devices": 0,
        "reminders": {"state": "normal", "since": None, "learned_time": None, "time_chosen": False},
    }
    assert (
        client.post("/api/users/push/subscriptions/", sub_body(), format="json").data["code"]
        == "push_disabled"
    )
    assert client.post("/api/users/push/test/").data["code"] == "push_disabled"


@pytest.mark.django_db
def test_subscribe_status_and_unsubscribe(auth, vapid):
    client, _ = auth
    r = client.post("/api/users/push/subscriptions/", sub_body(), format="json", HTTP_USER_AGENT="Chrome")
    assert r.status_code == 201 and r.data["devices"] == 1
    st = client.get("/api/users/push/").data
    assert st["enabled"] and st["public_key"] == "BPublicKeyForTests" and st["subscribed"]
    # Same endpoint again updates, never duplicates.
    client.post("/api/users/push/subscriptions/", sub_body(), format="json")
    assert PushSubscription.objects.count() == 1
    assert client.delete("/api/users/push/subscriptions/", {}, format="json").status_code == 400
    assert (
        client.delete("/api/users/push/subscriptions/", {"endpoint": FCM}, format="json").status_code == 204
    )
    assert not PushSubscription.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "endpoint",
    [
        "http://fcm.googleapis.com/fcm/send/x",  # not https
        "https://evil.example.com/push",  # not a push service
        "https://fcm.googleapis.com.evil.com/x",  # suffix trick
        "https://localhost/x",
        "https://169.254.169.254/latest",
        "https://user:pw@fcm.googleapis.com/x",  # credentials in the URL
        "https://fcm.googleapis.com:8443/x",  # odd port
        "https://notify.windows.com/x",  # the wildcard needs a subdomain
        "https://fcm.googleapis.com/" + "a" * 1000,  # too long
        "",
        None,
        123,
    ],
)
def test_bad_endpoints_refused(auth, vapid, endpoint):
    client, _ = auth
    r = client.post("/api/users/push/subscriptions/", sub_body(endpoint=endpoint), format="json")
    assert r.status_code == 400 and r.data["code"] == "bad_endpoint"


def test_allowlist_accepts_the_browser_services(vapid):
    for e in (
        FCM,
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://wns2-par02p.notify.windows.com/w/?token=x",
        "https://web.push.apple.com/QGx",
        "https://api.push.apple.com/3/device/x",
    ):
        assert push.endpoint_allowed(e), e


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("p256dh", "auth_key"),
    [
        ("not base64 !!", AUTH),
        (base64.urlsafe_b64encode(b"\x04" * 10).decode(), AUTH),  # wrong length
        (P256, base64.urlsafe_b64encode(b"x" * 8).decode()),
        (P256, None),
        ("", AUTH),
    ],
)
def test_bad_keys_refused(auth, vapid, p256dh, auth_key):
    client, _ = auth
    r = client.post("/api/users/push/subscriptions/", sub_body(p256dh=p256dh, auth=auth_key), format="json")
    assert r.status_code == 400 and r.data["code"] == "bad_keys"


@pytest.mark.django_db
def test_at_most_ten_devices_oldest_dropped(vapid):
    u = _user()
    for i in range(12):
        push.subscribe(u, f"{FCM}{i}", P256, AUTH)
    eps = set(PushSubscription.objects.filter(user=u).values_list("endpoint", flat=True))
    assert len(eps) == 10 and f"{FCM}0" not in eps and f"{FCM}1" not in eps and f"{FCM}11" in eps


@pytest.mark.django_db
def test_endpoint_moves_to_the_account_now_signed_in(vapid):
    a, b = _user("a@example.com"), _user("b@example.com")
    push.subscribe(a, FCM, P256, AUTH)
    push.subscribe(b, FCM, P256, AUTH)
    assert PushSubscription.objects.get(endpoint=FCM).user == b and PushSubscription.objects.count() == 1


@pytest.mark.django_db
def test_throttled(auth, vapid):
    client, _ = auth
    codes = [
        client.post(
            "/api/users/push/subscriptions/", sub_body(endpoint=f"{FCM}{i}"), format="json"
        ).status_code
        for i in range(31)
    ]
    assert codes[:30] == [201] * 30 and codes[30] == 429


@pytest.mark.django_db
def test_send_respects_prefs_and_payload_is_safe(sent):
    calls, _ = sent
    u = _user()
    assert push.send(u, "study", "Hi", "Body", "/today") is False  # no device yet
    push.subscribe(u, FCM, P256, AUTH)
    assert push.send(u, "study", "Study time", "Body", "https://evil.example.com/") is True
    import json

    payload = json.loads(calls[-1]["data"])
    token = payload.pop("id")  # the per-push open-tracking token (PushLog), random and short-lived
    assert PushLog.objects.get(token=token).kind == "study" and len(token) >= 16
    assert payload == {
        "title": "Study time",
        "body": "Body",
        "url": "/",
        "kind": "study",
        "tag": "aasan-study",
    }
    assert calls[-1]["claims"]["sub"] == "mailto:test@example.com"
    assert (
        push.send(u, "study", "x", "y", "//evil.example.com") and json.loads(calls[-1]["data"])["url"] == "/"
    )
    p = u.preferences
    p.data = {**p.data, "notifications": {**p.data["notifications"], "push_study": False}}
    p.save()
    n = len(calls)
    assert push.send(u, "study", "x") is False and push.send(u, "winback", "x") is False
    assert push.send(u, "plan", "x") is True and len(calls) == n + 1
    assert push.send(u, "unknown_kind", "x") is False


@pytest.mark.django_db
def test_send_never_raises(monkeypatch, vapid):
    u = _user()
    push.subscribe(u, FCM, P256, AUTH)
    from apps.accounts import tasks

    def boom(*a, **k):
        raise ConnectionError("broker down")

    monkeypatch.setattr(tasks.push_deliver, "delay", boom)
    assert push.send(u, "study", "x") is False


@pytest.mark.django_db
def test_delivery_failures(sent):
    calls, outcome = sent
    u = _user()
    gone, flaky, ok = f"{FCM}gone", f"{FCM}flaky", f"{FCM}ok"
    for e in (gone, flaky, ok):
        push.subscribe(u, e, P256, AUTH)
    outcome[gone] = 410
    outcome[flaky] = 500
    assert push.deliver(u.id, {"title": "t"}) == 1
    assert not PushSubscription.objects.filter(endpoint=gone).exists()
    assert PushSubscription.objects.get(endpoint=flaky).failures == 1
    assert PushSubscription.objects.get(endpoint=ok).last_used_at is not None
    outcome[flaky] = ConnectionError("timeout")
    for _ in range(4):
        push.deliver(u.id, {"title": "t"})
    assert not PushSubscription.objects.filter(endpoint=flaky).exists()  # dropped after 5 failures in a row
    outcome[ok] = 404
    push.deliver(u.id, {"title": "t"})
    assert not PushSubscription.objects.filter(user=u).exists()


@pytest.mark.django_db
def test_delivery_skips_endpoints_no_longer_allowed(sent, settings):
    calls, _ = sent
    u = _user()
    push.subscribe(u, FCM, P256, AUTH)
    settings.WEBPUSH_ENDPOINT_HOSTS = ["web.push.apple.com"]
    assert push.deliver(u.id, {"title": "t"}) == 0 and not calls
    assert not PushSubscription.objects.exists()


@pytest.mark.django_db
def test_test_endpoint(auth, sent):
    calls, _ = sent
    client, _ = auth
    assert client.post("/api/users/push/test/").data["code"] == "not_subscribed"
    client.post("/api/users/push/subscriptions/", sub_body(), format="json")
    assert client.post("/api/users/push/test/").status_code == 200 and len(calls) == 1


@pytest.mark.django_db
def test_password_reset_and_logout_remove_subscriptions(vapid, client):
    from apps.accounts.tokens import revoke_all_sessions

    u = _user()
    push.subscribe(u, FCM, P256, AUTH)
    revoke_all_sessions(u, "password_reset")
    assert not PushSubscription.objects.exists()
    push.subscribe(u, FCM, P256, AUTH)
    assert client.post("/api/users/logout/", {"push_endpoint": FCM}, format="json").status_code == 204
    assert not PushSubscription.objects.exists()


@pytest.mark.django_db
def test_new_preferences_accepted_and_unsubscribe_covers_winback(auth):
    client, _ = auth
    r = client.patch("/api/users/preferences/", {"notifications": {"push_streak": False}}, format="json")
    assert r.status_code == 200 and r.data["notifications"]["push_streak"] is False
    assert r.data["notifications"]["email_winback"] is True
    from apps.accounts.notify import CATEGORIES, unsubscribe, unsubscribe_url

    assert "email_winback" in CATEGORIES
    u = User.objects.get(email="kavya@example.com")
    token = unsubscribe_url(u, "email_winback").split("t=")[1]
    assert unsubscribe(token) == (True, "email_winback")


# ── Hooks: one push per reminder path ──


@pytest.fixture
def spy(monkeypatch, vapid):
    calls = []
    monkeypatch.setattr(
        push, "send", lambda user, kind, title, body="", url="/", **kw: calls.append((user.id, kind, url))
    )
    return calls


@pytest.mark.django_db
def test_study_reminder_pushes(spy):
    from apps.accounts.study_reminders import send_due

    u = _user()
    now = timezone.make_aware(
        datetime.combine(timezone.localdate(), datetime.min.time()).replace(hour=19, minute=5)
    )
    p = u.preferences
    p.data = {
        **p.data,
        "learning": {**p.data["learning"], "reminder_times": ["19:00"], "study_days": list(range(7))},
    }
    p.save()
    # 19:00 is the default, not a choice: the reminder goes at the nudge time (30 minutes earlier) instead.
    assert send_due(now) == 0
    assert send_due(now.replace(hour=18, minute=35)) == 1
    assert (u.id, "study", "/today") in spy
    # A learner who picked 19:00 gets it exactly then.
    chosen = _user("chosen@example.com")
    ReminderState.objects.create(user=chosen, time_chosen=True)
    assert send_due(now.replace(hour=18, minute=35)) == 0 and send_due(now) == 1
    assert (chosen.id, "study", "/today") in spy


@pytest.mark.django_db
def test_workshop_tell_pushes(spy):
    from apps.workshops.content import seed
    from apps.workshops.models import Workshop, WorkshopRun
    from apps.workshops.public import tell

    seed()
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug="quick-check"), audience="public", starts_at=timezone.now()
    )
    u = _user()
    tell(u, "Starts soon", "In 15 minutes", run, email=False)
    assert spy and spy[0][:2] == (u.id, "workshops")


@pytest.mark.django_db
def test_teacher_nudge_pushes(spy):
    from rest_framework.test import APIClient

    from apps.orgs.models import Membership, Organization

    org = Organization.objects.create(name="School", slug="school")
    teacher, learner = _user("t@example.com"), _user("l@example.com")
    Membership.objects.create(org=org, user=teacher, role="manager")
    Membership.objects.create(org=org, user=learner, role="learner")
    c = APIClient()
    c.force_authenticate(teacher)
    assert c.post("/api/orgs/school/nudge/", {"user_ids": [learner.id]}, format="json").data["nudged"] == 1
    assert (learner.id, "teacher", "/learn") in spy


@pytest.mark.django_db
def test_plan_reminder_pushes(spy):
    from apps.billing.models import Entitlement, Plan
    from apps.billing.reminders import send_due

    u = _user()
    plan = Plan.objects.exclude(code="free").first()
    Entitlement.objects.create(
        user=u,
        plan=plan,
        starts_at=timezone.now() - timedelta(days=28),
        ends_at=timezone.now() + timedelta(days=2),
    )
    assert send_due()["soon"] == 1
    assert (u.id, "plan", "/plans") in spy


# ── Evening check ──


def _at(hour):
    return timezone.make_aware(datetime.combine(timezone.localdate(), datetime.min.time()).replace(hour=hour))


@pytest.mark.django_db
def test_evening_check_streak_and_reviews_once_a_day(sent):
    calls, _ = sent
    from apps.accounts.evening import run
    from apps.game.models import Notification, PlayerStats

    u, nosub = _user(), _user("nosub@example.com")
    push.subscribe(u, FCM, P256, AUTH)
    for x in (u, nosub):
        PlayerStats.objects.create(user=x, streak=5, last_active=timezone.localdate() - timedelta(days=1))
    assert run(_at(12)) == {"streak": 0, "reviews": 0}  # before the nudge time (18:30)
    assert run(_at(19)) == {"streak": 1, "reviews": 0}
    assert run(_at(20)) == {"streak": 0, "reviews": 0}  # idempotent
    assert Notification.objects.filter(user=u, kind="streak_risk").count() == 1
    assert not Notification.objects.filter(user=nosub).exists()  # only learners with a device
    assert len(calls) == 1
    # The companion speaks (anna_akka by default), the streak is in the copy, and bell and push say the same.
    import json

    n = Notification.objects.get(user=u, kind="streak_risk")
    payload = json.loads(calls[0]["data"])
    assert "5" in n.title + n.body and payload["title"] == n.title and payload["body"] == n.body
    assert PushLog.objects.get(token=payload["id"]).moment == "streak_risk"


@pytest.mark.django_db
def test_evening_follows_the_learned_time_and_never_runs_at_night(sent):
    from apps.accounts.evening import run
    from apps.game.models import PlayerStats

    u = _user()
    push.subscribe(u, FCM, P256, AUTH)
    PlayerStats.objects.create(user=u, streak=5, last_active=timezone.localdate() - timedelta(days=1))
    ReminderState.objects.create(user=u, best_minute=9 * 60)  # usually studies at 09:00 → nudge from 08:30
    assert run(_at(8))["streak"] == 0
    assert run(_at(9))["streak"] == 1
    late = _user("late@example.com")
    push.subscribe(late, f"{FCM}late", P256, AUTH)
    PlayerStats.objects.create(user=late, streak=3, last_active=timezone.localdate() - timedelta(days=1))
    ReminderState.objects.create(user=late, best_minute=23 * 60 + 30)  # night owl: capped at 21:30
    assert run(_at(21))["streak"] == 0
    assert run(_at(23))["streak"] == 0  # quiet hours
    assert run(_at(21).replace(minute=30))["streak"] == 1


@pytest.mark.django_db
def test_evening_check_reviews_due(sent, monkeypatch):
    from apps.accounts import evening

    u = _user()
    push.subscribe(u, FCM, P256, AUTH)

    class Q:
        def filter(self, **kw):
            return self

        def count(self):
            return 7

    import apps.review.models as rm

    monkeypatch.setattr(rm.ReviewCard, "objects", Q())
    assert evening.run(_at(18))["reviews"] == 0  # before the default nudge time (18:30)
    assert evening.run(_at(19))["reviews"] == 1
    assert evening.run(_at(19))["reviews"] == 0


@pytest.mark.django_db
def test_evening_check_skips_away_mode(sent, monkeypatch):
    from apps.accounts.evening import run
    from apps.game.models import PlayerStats

    u = _user()
    push.subscribe(u, FCM, P256, AUTH)
    PlayerStats.objects.create(user=u, streak=5, last_active=timezone.localdate() - timedelta(days=1))
    monkeypatch.setattr("apps.study.planner.paused_on", lambda uid, d: True)
    assert run(_at(19)) == {"streak": 0, "reviews": 0}


def test_setup_env_writes_vapid_keys(tmp_path, settings):
    from io import StringIO

    from django.core.management import call_command

    settings.BASE_DIR = tmp_path
    (tmp_path / ".env.example").write_text("WEBPUSH_VAPID_PUBLIC_KEY=\nWEBPUSH_VAPID_PRIVATE_KEY=\n")
    out = StringIO()
    call_command("setup_env", stdout=out)
    values = dict(line.split("=", 1) for line in (tmp_path / ".env").read_text().splitlines() if "=" in line)
    pub, priv = values["WEBPUSH_VAPID_PUBLIC_KEY"], values["WEBPUSH_VAPID_PRIVATE_KEY"]
    assert len(base64.urlsafe_b64decode(pub + "==")) == 65 and len(base64.urlsafe_b64decode(priv + "=")) == 32
    assert priv not in out.getvalue()
    from py_vapid import Vapid

    assert Vapid.from_string(priv).sign({"sub": "mailto:a@example.com", "aud": "https://fcm.googleapis.com"})
    # A second run with one half present never invents a mismatched pair.
    (tmp_path / ".env").write_text("WEBPUSH_VAPID_PUBLIC_KEY=keep\n")
    call_command("setup_env", stdout=StringIO())
    assert "WEBPUSH_VAPID_PRIVATE_KEY=\n" in (tmp_path / ".env").read_text()
