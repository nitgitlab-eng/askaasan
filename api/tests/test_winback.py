"""Win-back: 3/7/30-day milestones, every skip rule, idempotency across reruns and new episodes, the streak-revive
offer, and the plan-lapse promo (guards, missing / expired / used-up code, never in push)."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounts import push, winback
from apps.accounts.models import User, WinbackSend
from apps.game.models import Notification, PlayerStats

TODAY = timezone.localdate


@pytest.fixture
def pushes(monkeypatch):
    calls = []
    monkeypatch.setattr(
        push,
        "send",
        lambda user, kind, title, body="", url="/", **kw: calls.append((user.id, kind, body, url, title, kw)),
    )
    return calls


def lapsed(email="w@example.com", days=3, streak=0, **kw):
    u = User.objects.create_user(email, "Winback#2026pw", email_verified=True)
    u.profile.display_name = "Meena Kumar"
    u.profile.save()
    PlayerStats.objects.create(
        user=u, last_active=TODAY() - timedelta(days=days), streak=streak, freezes=0, **kw
    )
    return u


@pytest.mark.django_db
@pytest.mark.parametrize(("days", "kind"), [(3, "inactive_3"), (7, "inactive_7"), (30, "inactive_30")])
def test_milestones_send_email_bell_and_push(days, kind, pushes):
    u = lapsed(days=days)
    out = winback.inactive()
    assert out[kind] == 1 and sum(out.values()) == 1
    assert WinbackSend.objects.get(user=u).kind == kind
    assert len(mail.outbox) == 1 and mail.outbox[0].to == [u.email] and "Meena" in mail.outbox[0].subject
    assert "unsubscribe" in mail.outbox[0].body.lower()
    assert Notification.objects.filter(user=u, kind="winback").count() == 1
    assert pushes and pushes[0][:2] == (u.id, "winback")
    # Push and bell speak in the companion's voice (voice.py); the email keeps its own subject.
    bell = Notification.objects.get(user=u, kind="winback")
    assert pushes[0][5]["moment"] == f"winback_{days}" and pushes[0][5]["variant"].startswith(
        f"winback_{days}."
    )
    assert (bell.title, bell.body) == (pushes[0][4], pushes[0][2]) and bell.title != mail.outbox[0].subject


@pytest.mark.django_db
@pytest.mark.parametrize("days", [1, 2, 4, 6, 8, 29, 31])
def test_other_gaps_are_left_alone(days, pushes):
    lapsed(days=days)
    assert sum(winback.inactive().values()) == 0 and not mail.outbox


@pytest.mark.django_db
def test_skips(pushes, monkeypatch):
    lapsed("unverified@example.com")
    User.objects.filter(email="unverified@example.com").update(email_verified=False)
    lapsed("inactive@example.com")
    User.objects.filter(email="inactive@example.com").update(is_active=False)
    lapsed("recent@example.com")  # opened the app yesterday (token refresh) but didn't study: don't nag
    User.objects.filter(email="recent@example.com").update(last_login=timezone.now() - timedelta(days=1))
    optout = lapsed("optout@example.com")
    p = optout.preferences
    p.data = {**p.data, "notifications": {**p.data["notifications"], "email_winback": False}}
    p.save()
    quiet = lapsed("quiet@example.com")  # got a win-back mail yesterday (another episode)
    WinbackSend.objects.create(user=quiet, kind="plan_lapse", episode=TODAY() - timedelta(days=20))
    away = lapsed("away@example.com")
    monkeypatch.setattr("apps.study.planner.paused_on", lambda uid, d: uid == away.id)
    lapsed("ok@example.com")
    User.objects.filter(email="ok@example.com").update(last_login=timezone.now() - timedelta(days=3))
    assert winback.inactive()["inactive_3"] == 1
    assert [m.to for m in mail.outbox] == [["ok@example.com"]]


@pytest.mark.django_db
def test_idempotent_across_reruns_and_new_episodes(pushes):
    u = lapsed(days=3)
    assert winback.inactive()["inactive_3"] == 1
    assert winback.inactive()["inactive_3"] == 0  # same day rerun / Celery retry
    # Four days later (7 days away) the 2-day quiet rule has passed: the 7-day mail goes out once.
    later = timezone.now() + timedelta(days=4)
    assert winback.inactive(later)["inactive_7"] == 1
    assert winback.inactive(later)["inactive_7"] == 0
    # They came back, then lapsed again: a new episode starts the milestones over.
    much_later = timezone.now() + timedelta(days=20)
    PlayerStats.objects.filter(user=u).update(last_active=timezone.localdate(much_later) - timedelta(days=3))
    assert winback.inactive(much_later)["inactive_3"] == 1
    assert WinbackSend.objects.filter(user=u).count() == 3


@pytest.mark.django_db
def test_personal_lines_and_revive_offer(pushes):
    u = lapsed(days=7, streak=6, best_streak=6)
    winback.inactive()
    body = mail.outbox[0].body
    assert "Bring back your 6-day streak" in body and "/achievements?repair=1" in body
    assert pushes[0][3] == "/achievements?repair=1"
    s = PlayerStats.objects.get(user=u)
    # The repair window starts with the email; the revival window waits for them to come back.
    assert s.broken_at == TODAY() and s.last_streak == 6 and s.streak == 6 and s.revive_started_at is None
    from apps.game.api import _status

    offer = _status(u)["repair"]
    assert offer["last_streak"] == 6 and offer["revive_open"]


@pytest.mark.django_db
def test_no_revive_offer_for_short_streaks_or_three_day_mail(pushes):
    lapsed("short@example.com", days=7, streak=2)
    lapsed("three@example.com", days=3, streak=9)
    winback.inactive()
    assert all("streak" not in m.body.lower() or "repair" not in m.body for m in mail.outbox)
    assert not PlayerStats.objects.filter(broken_at__isnull=False).exists()


@pytest.mark.django_db
def test_thirty_day_mail_reopens_an_old_unused_offer(pushes):
    u = lapsed(days=30, streak=8, last_streak=8, broken_at=TODAY() - timedelta(days=25))
    winback.inactive()
    assert "8-day streak" in mail.outbox[0].body
    assert PlayerStats.objects.get(user=u).broken_at == TODAY()


@pytest.mark.django_db
def test_tamil_mail(pushes):
    u = lapsed(days=3)
    u.profile.language = "ta"
    u.profile.save()
    winback.inactive()
    assert "பாடங்கள்" in mail.outbox[0].subject


# ── Plan lapse ──


@pytest.fixture
def plan(db):
    from apps.billing.models import Plan

    return Plan.objects.exclude(code="free").order_by("price_paise").first()


def promo(**kw):
    from apps.billing.models import PromoCode

    return PromoCode.objects.create(
        code=kw.pop("code", "COMEBACK30"), kind="percent", value=30, purpose="winback_lapse", **kw
    )


def ended(user, plan, days_ago=5, source="payment"):
    from apps.billing.models import Entitlement

    end = timezone.now() - timedelta(days=days_ago)
    return Entitlement.objects.create(
        user=user, plan=plan, starts_at=end - timedelta(days=30), ends_at=end, source=source
    )


def payer(email="payer@example.com"):
    return User.objects.create_user(email, "Winback#2026pw", email_verified=True)


@pytest.mark.django_db
def test_plan_lapse_sends_one_promo_email(plan, pushes):
    p = promo()
    u = payer()
    ended(u, plan)
    assert winback.plan_lapse() == 1
    m = mail.outbox[0]
    assert "COMEBACK30" in m.body and "30% off" in m.subject
    ws = WinbackSend.objects.get(user=u, kind="plan_lapse")
    assert ws.promo == p
    bell = Notification.objects.get(user=u, kind="winback")
    assert "COMEBACK30" not in bell.title + bell.body  # the code is only in the email
    assert not pushes  # never in push
    assert winback.plan_lapse() == 0  # rerun
    # A later lapse within 180 days gets nothing.
    WinbackSend.objects.update(sent_at=timezone.now() - timedelta(days=100))
    ended(u, plan, days_ago=4)
    assert winback.plan_lapse() == 0


@pytest.mark.django_db
def test_plan_lapse_guards(plan, pushes):
    from apps.billing.models import Entitlement, Subscription

    promo()
    too_soon = payer("soon@example.com")
    ended(too_soon, plan, days_ago=1)
    too_old = payer("old@example.com")
    ended(too_old, plan, days_ago=12)
    granted = payer("grant@example.com")
    ended(granted, plan, source="grant")  # a free grant isn't a lost customer
    renewed = payer("renewed@example.com")
    ended(renewed, plan)
    Entitlement.objects.create(
        user=renewed, plan=plan, starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=30)
    )
    autorenew = payer("auto@example.com")
    ended(autorenew, plan)
    Subscription.objects.create(user=autorenew, plan=plan, status="active", rp_subscription_id="sub_x")
    optout = payer("optout@example.com")
    ended(optout, plan)
    p = optout.preferences
    p.data = {**p.data, "notifications": {**p.data["notifications"], "email_winback": False}}
    p.save()
    ok = payer("ok@example.com")
    ended(ok, plan)
    assert winback.plan_lapse() == 1
    assert [m.to for m in mail.outbox] == [["ok@example.com"]]


@pytest.mark.django_db
def test_plan_lapse_skips_school_seats(plan, pushes, monkeypatch):
    promo()
    u = payer()
    ended(u, plan)
    monkeypatch.setattr("apps.billing.services.seat_plan", lambda user: plan)
    assert winback.plan_lapse() == 0


@pytest.mark.django_db
@pytest.mark.parametrize(
    "kw",
    [
        None,  # no code at all
        {"expires_at": timezone.now() - timedelta(days=1)},
        {"active": False},
        {"max_uses": 5, "uses": 5},
        {"purpose": ""},  # an ordinary checkout code is never mailed
    ],
)
def test_plan_lapse_needs_a_usable_promo(plan, pushes, kw):
    from apps.billing.models import PromoCode

    if kw is not None:
        purpose = kw.pop("purpose", "winback_lapse")
        PromoCode.objects.create(code="OLD", kind="percent", value=20, purpose=purpose, **kw)
    ended(payer(), plan)
    assert winback.plan_lapse() == 0 and not mail.outbox and not WinbackSend.objects.exists()


@pytest.mark.django_db
def test_newest_promo_wins_and_fixed_amounts_read_in_rupees(plan, pushes):
    promo(code="FIRST")
    promo(code="FLAT100", expires_at=timezone.now() + timedelta(days=10))
    from apps.billing.models import PromoCode

    PromoCode.objects.filter(code="FLAT100").update(kind="fixed", value=10000)
    ended(payer(), plan)
    winback.plan_lapse()
    assert "FLAT100" in mail.outbox[0].body and "₹100 off" in mail.outbox[0].subject


@pytest.mark.django_db
def test_admin_can_mark_a_code_for_winback(client):
    from apps.billing.models import PromoCode

    admin = User.objects.create_user("admin@example.com", "Admin#2026pass", is_staff=True)
    client.force_authenticate(admin)
    r = client.post(
        "/api/admin/promos/",
        {"code": "back20", "kind": "percent", "value": 20, "purpose": "winback_lapse"},
        format="json",
    )
    assert r.status_code == 201 and r.data["purpose"] == "winback_lapse"
    pk = r.data["id"]
    assert client.patch(f"/api/admin/promos/{pk}/", {"purpose": "nonsense"}, format="json").status_code == 400
    assert client.patch(f"/api/admin/promos/{pk}/", {"purpose": ""}, format="json").data["purpose"] == ""
    assert PromoCode.objects.get(pk=pk).purpose == ""


@pytest.mark.django_db
def test_run_reports_both(plan, pushes):
    lapsed(days=3)
    promo()
    ended(payer(), plan)
    assert winback.run() == {
        "inactive": {"inactive_3": 1, "inactive_7": 0, "inactive_30": 0},
        "plan_lapse": 1,
    }
