"""Fix pass (agent E): plan limits, seats, promos, reminders, voice charging, guest AI pool, Razorpay hardening."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import (
    Entitlement,
    Order,
    OrgSubscription,
    Plan,
    PromoCode,
    Subscription,
    UsageEvent,
    WebhookEvent,
)
from apps.billing.services import PlanLimit, consume, current_plan, extend_org, grant_for_order, seats_total
from apps.orgs.models import Membership, Organization
from apps.providers.models import ProviderConfig, UsageCounter

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"
PW = "Fix#Billing2026"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def sign(msg, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


def paid_plan(code="seat_p", price=10000, days=30):
    return Plan.objects.create(code=code, name=code.upper(), price_paise=price, period_days=days, limits={})


def org_with_learners(n=3, slug="acme"):
    org = Organization.objects.create(name=slug.title(), slug=slug, kind="school")
    learners = [User.objects.create_user(f"l{i}@{slug}.in", PW) for i in range(n)]
    for u in learners:
        Membership.objects.create(org=org, user=u, role="learner")
    return org, learners


# ── R34: atomic check-and-record ─────────────────────────────────────


def test_consume_records_atomically_and_stops_at_the_limit():
    _, u = client_for("c@x.in")
    free = Plan.objects.get(code="free")
    free.limits = {**free.limits, "lab_ai_per_day": 3}
    free.save()
    consume(u, "lab_ai_per_day", "lab_ai", 2)
    with pytest.raises(PlanLimit):
        consume(u, "lab_ai_per_day", "lab_ai", 2)  # 2 + 2 > 3: nothing recorded for the refused call
    assert UsageEvent.objects.filter(user=u, metric="lab_ai").count() == 2
    consume(u, "lab_ai_per_day", "lab_ai")
    assert UsageEvent.objects.filter(user=u, metric="lab_ai").count() == 3


def test_free_plan_fallback_is_not_unlimited():
    from apps.billing.services import free_plan

    Plan.objects.filter(code="free").update(code="free_old")
    assert (
        free_plan().limits.get("ai_courses_per_month") == 2 and free_plan().limits.get("lab_ai_per_day") == 20
    )


# ── S21 / R48 / R35: seats ───────────────────────────────────────────


def test_seats_beyond_the_paid_count_give_no_plan():
    org, learners = org_with_learners(3)
    p = paid_plan()
    big = extend_org(org, p, 3)
    assert Membership.objects.filter(org=org, seat=True).count() == 3
    big.ends_at = timezone.now() - timedelta(minutes=1)
    big.save()
    extend_org(org, p, 1)
    assert seats_total(org) == 1
    assert [current_plan(u).code for u in learners].count(p.code) == 1  # only one paid seat


def test_one_pricier_seat_does_not_upgrade_every_seat_holder():
    org, learners = org_with_learners(3)
    p, q = paid_plan("seat_p", 10000), paid_plan("seat_q", 50000)
    now = timezone.now()
    # Overlapping subscriptions (e.g. from before the fix): 3 seats of P and 1 of Q.
    OrgSubscription.objects.create(org=org, plan=p, seats=3, starts_at=now, ends_at=now + timedelta(days=30))
    OrgSubscription.objects.create(org=org, plan=q, seats=1, starts_at=now, ends_at=now + timedelta(days=30))
    Membership.objects.filter(org=org).update(seat=True)
    assert {current_plan(u).code for u in learners} == {p.code}


def test_different_size_renewal_credits_unused_time_and_replaces_old_sub():
    org, _ = org_with_learners(2)
    p = paid_plan(days=30)
    order = Order.objects.create(
        org=org,
        plan=p,
        seats=10,
        amount_paise=100000,
        list_paise=100000,
        rp_order_id="order_r_size",
        status="paid",
    )
    old = extend_org(org, p, 10, order=order)  # credit follows what was paid (S21): here the full list price
    old.starts_at, old.ends_at = timezone.now() - timedelta(days=15), timezone.now() + timedelta(days=15)
    old.save()
    new = extend_org(org, p, 5)  # half the old value left (10 seats × 15 days) = 30 days of 5 seats
    old.refresh_from_db()
    assert old.ends_at <= timezone.now() + timedelta(seconds=5)  # no longer running alongside
    assert abs((new.ends_at - new.starts_at) - timedelta(days=60)) < timedelta(minutes=1)
    assert seats_total(org) == 5


def test_same_size_renewal_still_stacks():
    org, _ = org_with_learners(1)
    p = paid_plan(days=30)
    a = extend_org(org, p, 2)
    b = extend_org(org, p, 2)
    assert b.starts_at == a.ends_at and OrgSubscription.objects.get(pk=a.pk).ends_at == a.ends_at


def test_org_billing_seat_toggle_parses_input():
    org, learners = org_with_learners(1)
    admin, au = client_for("boss@acme.in")
    Membership.objects.create(org=org, user=au, role="owner")
    extend_org(org, paid_plan(), 1)
    m = Membership.objects.get(user=learners[0])
    assert m.seat
    assert (
        admin.post(
            "/api/billing/orgs/acme/", {"membership_id": "abc", "seat": True}, format="json"
        ).status_code
        == 400
    )  # R41
    r = admin.post(
        "/api/billing/orgs/acme/", {"membership_id": str(m.id), "seat": "false"}, format="json"
    )  # R57
    assert r.status_code == 200
    m.refresh_from_db()
    assert not m.seat


# ── S20: promo limits re-checked at capture ──────────────────────────


def test_failed_then_paid_promo_order_cannot_exceed_per_user(keys, gateway):
    PromoCode.objects.create(code="P", kind="percent", value=90, per_user=1)
    c, u = client_for("buyer@x.in")
    a = c.post("/api/billing/checkout/", {"plan": "plus_month", "promo": "P"}, format="json")
    assert a.status_code == 201
    c.post("/api/billing/failed/", {"razorpay_order_id": a.data["order_id"]}, format="json")
    b = c.post("/api/billing/checkout/", {"plan": "plus_month", "promo": "P"}, format="json")
    assert b.status_code == 201
    oa, ob = (
        Order.objects.get(rp_order_id=a.data["order_id"]),
        Order.objects.get(rp_order_id=b.data["order_id"]),
    )
    assert grant_for_order(ob.id, "pay_b") is not None
    assert grant_for_order(oa.id, "pay_a") is None
    oa.refresh_from_db()
    assert oa.status != "paid" and oa.error == "promo_used_up"
    assert PromoCode.objects.get(code="P").uses == 1 and Entitlement.objects.filter(user=u).count() == 1


def test_stale_promo_order_paid_after_max_uses_is_not_granted(keys, gateway):
    PromoCode.objects.create(code="ONE", kind="percent", value=50, max_uses=1, per_user=5)
    c1, _ = client_for("first@x.in")
    c2, u2 = client_for("second@x.in")
    a = c1.post("/api/billing/checkout/", {"plan": "plus_month", "promo": "ONE"}, format="json")
    Order.objects.filter(rp_order_id=a.data["order_id"]).update(
        created_at=timezone.now() - timedelta(minutes=31)
    )
    oid = c2.post("/api/billing/checkout/", {"plan": "plus_month", "promo": "ONE"}, format="json").data[
        "order_id"
    ]
    gateway[1]["status"] = "captured"
    assert (
        c2.post(
            "/api/billing/verify/",
            {"razorpay_order_id": oid, "razorpay_payment_id": "p2", "razorpay_signature": sign(f"{oid}|p2")},
            format="json",
        ).status_code
        == 200
    )
    oa = Order.objects.get(rp_order_id=a.data["order_id"])
    assert grant_for_order(oa.id, "p1") is None and PromoCode.objects.get(code="ONE").uses == 1


# ── Razorpay hardening ───────────────────────────────────────────────


def test_verify_does_not_grant_until_capture_is_confirmed(keys, gateway, monkeypatch):
    from apps.billing import razorpay as rp

    c, u = client_for("a@x.in")
    oid = c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").data["order_id"]

    def down(*a):
        raise rp.RazorpayError("timeout")

    monkeypatch.setattr(rp, "fetch_payment", down)
    r = c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": "p", "razorpay_signature": sign(f"{oid}|p")},
        format="json",
    )
    assert r.status_code == 502 and current_plan(u).code == "free"


def test_webhook_replayed_with_a_new_event_id_is_a_duplicate(keys, gateway):
    c, u = client_for("a@x.in")
    oid = c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").data["order_id"]
    body = json.dumps(
        {
            "event": "order.paid",
            "payload": {"payment": {"entity": {"id": "pay_w", "order_id": oid, "amount": 14900}}},
        }
    ).encode()
    post = lambda eid: APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK),
        HTTP_X_RAZORPAY_EVENT_ID=eid,
    )
    assert post("evt_a").status_code == 200
    assert post("evt_b").data.get("duplicate") is True
    assert WebhookEvent.objects.filter(event_id="evt_a").exists()


def test_org_checkout_description_pluralises_seats(keys, gateway):
    org, _ = org_with_learners(1)
    admin, au = client_for("boss@acme.in")
    Membership.objects.create(org=org, user=au, role="owner")
    assert (
        admin.post("/api/billing/checkout/", {"plan": "plus_month", "org": "acme", "seats": 1}, format="json")
        .data["description"]
        .endswith("× 1 seat")
    )
    assert (
        admin.post("/api/billing/checkout/", {"plan": "plus_month", "org": "acme", "seats": 2}, format="json")
        .data["description"]
        .endswith("× 2 seats")
    )


# ── R45: reminders ───────────────────────────────────────────────────


def test_plan_reminders_skip_auto_renew_and_mention_seat_plans():
    from apps.billing.reminders import send_due
    from apps.game.models import Notification

    now = timezone.now()
    plus = Plan.objects.get(code="plus_month")
    renewer = User.objects.create_user("renew@x.in", PW)
    Entitlement.objects.create(
        user=renewer, plan=plus, starts_at=now - timedelta(days=28), ends_at=now + timedelta(days=2)
    )
    Subscription.objects.create(user=renewer, plan=plus, rp_subscription_id="sub_1", status="active")
    assert send_due(now) == {"soon": 0, "ended": 0}

    org, (seated,) = org_with_learners(1)
    cheap = paid_plan("seat_cheap", 5000)
    extend_org(org, cheap, 1)
    Entitlement.objects.create(
        user=seated, plan=plus, starts_at=now - timedelta(days=31), ends_at=now - timedelta(days=1)
    )
    assert send_due(now) == {"soon": 0, "ended": 1}
    n = Notification.objects.get(user=seated, kind="plan")
    assert "Free plan" not in n.body and cheap.name in n.body


# ── R49 / S12: voice charging ────────────────────────────────────────


@pytest.fixture
def stt(monkeypatch):
    import apps.providers.voice_api as v

    ProviderConfig.objects.create(
        capability="stt", provider="fake", model="x", limits={"stt_seconds_per_day": 100000}
    )
    monkeypatch.setattr(v, "needs_key", lambda *a: False)
    sent = []
    monkeypatch.setattr(v, "transcribe", lambda cfg, audio, mime, lang: sent.append(len(audio)) or "hi")
    return v, sent


def _secs(u):
    row = UsageCounter.objects.filter(user=u, metric="stt_seconds").first()
    return row.amount if row else 0


def test_stt_refunded_when_transcription_fails(stt, monkeypatch):
    from apps.providers.voice.adapters import VoiceError

    v, _ = stt

    def boom(*a):
        raise VoiceError("provider_error")

    monkeypatch.setattr(v, "transcribe", boom)
    c, u = client_for("v@x.in")
    r = c.post(
        "/api/voice/transcribe/",
        {"audio": SimpleUploadedFile("a.webm", b"0" * 40000, "audio/webm")},
        format="multipart",
    )
    assert r.status_code == 502 and _secs(u) == 0


def test_large_clip_is_charged_its_full_estimated_length(stt):
    _, sent = stt
    c, u = client_for("v@x.in")
    r = c.post(
        "/api/voice/transcribe/",
        {"audio": SimpleUploadedFile("a.webm", b"0" * 4_000_000, "audio/webm"), "seconds": "0"},
        format="multipart",
    )
    assert r.status_code == 402 and r.data["code"] == "plan_limit"  # ~5300 s > the free 10 min/day
    assert sent == [] and _secs(u) == 0
    r = c.post(
        "/api/voice/transcribe/",
        {"audio": SimpleUploadedFile("b.webm", b"0" * 400_000, "audio/webm")},
        format="multipart",
    )
    assert r.status_code == 200 and _secs(u) == 100  # charged its estimated length at 32 kbps (4000 B/s, S12)


# ── R41: admin overview ?days ────────────────────────────────────────


def test_admin_overview_ignores_bad_days():
    staff, _ = client_for("ops@x.in", is_staff=True)
    assert staff.get("/api/admin/overview/?days=abc").status_code == 200


# ── S6: guest AI pool ────────────────────────────────────────────────


def _rp_link(email, **kw):
    from apps.roleplay.models import Scenario

    c, u = client_for(email, is_creator=True, **kw)
    sc = Scenario.objects.create(
        owner=u,
        title="Pitch",
        summary="s",
        learner_role="student",
        character={"name": "A", "persona": "p", "goal": "g", "style": "s"},
        setting="x",
        objectives=["State the problem"],
        competencies=[{"name": "Simplicity", "description": "d"}],
        opening_line="So, what's your idea?",
        max_turns=10,
    )
    return c.post(
        "/api/guests/links/", {"label": "rp", "target_kind": "roleplay", "scenario_id": sc.id}, format="json"
    ).data["slug"], u


def _guest(slug, ip):
    g = APIClient(REMOTE_ADDR=ip)
    r = g.post(f"/api/guests/public/{slug}/start/", {}, format="json")
    g.credentials(HTTP_X_GUEST_TOKEN=r.data["token"])
    g.post(f"/api/guests/public/{slug}/role-play/", {}, format="json")
    return g


def test_throwaway_owners_cannot_drain_the_pool_for_others(settings):
    from apps.guests.models import GuestAIUsage

    (
        settings.GUEST_AI_GLOBAL_DAY,
        settings.GUEST_AI_PER_OWNER_DAY,
        settings.GUEST_AI_PER_LINK_DAY,
        settings.GUEST_AI_PER_IP_DAY,
    ) = 10, 4, 4, 2
    codes = []
    for i in range(3):  # three unverified free owners, guests from distinct /64s
        slug, _ = _rp_link(f"a{i}@x.in")
        for j in range(2):
            g = _guest(slug, f"2001:db8:{i}:{j}::1")
            codes += [
                g.post(f"/api/guests/public/{slug}/role-play/say/", {"text": "hi"}, format="json").status_code
                for _ in range(2)
            ]
    assert codes.count(200) == 2 and GuestAIUsage.objects.get(key="global:new").units == 2  # 20% of the pool
    slug_b, ub = _rp_link("b@x.in", email_verified=True)
    g = _guest(slug_b, "2001:db8:9:9::1")
    assert (
        g.post(f"/api/guests/public/{slug_b}/role-play/say/", {"text": "hi"}, format="json").status_code
        == 200
    )
