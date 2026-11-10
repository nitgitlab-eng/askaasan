"""Razorpay Subscriptions (auto-renew): create, verify, webhooks (signed + idempotent), charges → access + GST invoice,
pending/halted grace, cancel at period end, resume, permissions and admin mapping."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Entitlement, Invoice, Order, Plan, Subscription, WebhookEvent
from apps.billing.services import current_plan, paid_until
from apps.billing.subscriptions import mask_method

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"


def client_for(email, staff=False):
    u = User.objects.create_user(email, "Bill#2026passwd", is_staff=staff)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def sign(msg, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


@pytest.fixture
def renewable():
    Plan.objects.filter(code="plus_month").update(rp_plan_id="plan_TESTmonth01", auto_renew=True)
    return Plan.objects.get(code="plus_month")


def hook(event, sub_id, pay=None, event_id=None, sub_status="active"):
    payload = {
        "subscription": {
            "entity": {
                "id": sub_id,
                "status": sub_status,
                "current_start": 1_800_000_000,
                "current_end": 1_802_592_000,
                "charge_at": 1_802_592_000,
                "paid_count": 1,
            }
        }
    }
    if pay:
        payload["payment"] = {"entity": pay}
    body = json.dumps({"event": event, "payload": payload}).encode()
    headers = {"HTTP_X_RAZORPAY_SIGNATURE": sign(body, HOOK)}
    if event_id:
        headers["HTTP_X_RAZORPAY_EVENT_ID"] = event_id
    return APIClient().post("/api/billing/webhook/", body, content_type="application/json", **headers)


def subscribe(c, plan="plus_month", **extra):
    r = c.post("/api/billing/subscribe/", {"plan": plan, **extra}, format="json")
    assert r.status_code == 201, r.data
    return r.data["subscription_id"]


def captured(pid, amount=14900, **kw):
    return {
        "id": pid,
        "status": "captured",
        "amount": amount,
        "order_id": f"order_{pid}",
        "method": "upi",
        "vpa": "kavya.s@okhdfc",
        **kw,
    }


# ── Offer + create ───────────────────────────────────────────────────


def test_overview_marks_auto_renew_only_when_mapped(renewable):
    c, _ = client_for("a@x.in")
    plans = {p["code"]: p for p in c.get("/api/billing/").data["plans"]}
    assert plans["plus_month"]["auto_renew"] is True
    assert plans["plus_year"]["auto_renew"] is False and plans["free"]["auto_renew"] is False


def test_subscribe_needs_keys(renewable):
    c, _ = client_for("a@x.in")
    assert c.post("/api/billing/subscribe/", {"plan": "plus_month"}, format="json").status_code == 503


def test_subscribe_refuses_unmapped_plan_and_orgs(keys, sub_gateway, renewable):
    c, _ = client_for("a@x.in")
    assert c.post("/api/billing/subscribe/", {"plan": "plus_year"}, format="json").data["code"] == "bad_plan"
    assert (
        c.post("/api/billing/subscribe/", {"plan": "plus_month", "org": "x"}, format="json").data["code"]
        == "org_pay_once"
    )


def test_create_subscription_uses_server_plan_id(keys, sub_gateway, renewable):
    calls, _ = sub_gateway
    c, u = client_for("a@x.in")
    r = c.post("/api/billing/subscribe/", {"plan": "plus_month", "plan_id": "plan_EVIL"}, format="json")
    assert (
        r.status_code == 201
        and r.data["subscription_id"] == "sub_1"
        and r.data["key_id"] == "rzp_test_ABC123"
    )
    assert "secret" not in json.dumps(r.data).lower()
    assert calls["created"][0]["plan_id"] == "plan_TESTmonth01" and calls["created"][0]["total_count"] == 60
    s = Subscription.objects.get(user=u)
    assert s.status == "created" and s.amount_paise == 14900 and s.mode == "test"
    assert current_plan(u).code == "free"  # nothing until a charge lands


def test_only_one_live_subscription(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    subscribe(c)
    subscribe(c)  # an abandoned "created" one is replaced
    assert Subscription.objects.filter(user=u, status="created").count() == 1
    Subscription.objects.filter(user=u, status="created").update(status="active")
    assert c.post("/api/billing/subscribe/", {"plan": "plus_month"}, format="json").status_code == 409


# ── Browser callback ────────────────────────────────────────────────


def test_verify_grants_first_period_with_invoice(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    r = c.post(
        "/api/billing/subscription/verify/",
        {
            "razorpay_payment_id": "pay_s1",
            "razorpay_subscription_id": sid,
            "razorpay_signature": sign(f"pay_s1|{sid}"),
        },
        format="json",
    )
    assert r.status_code == 200 and r.data["subscription"]["status"] == "active"
    assert r.data["subscription"]["method"] == "Visa •••• 4242"
    assert current_plan(u).code == "plus_month"
    o = Order.objects.get(rp_payment_id="pay_s1")
    assert (
        o.status == "paid"
        and o.subscription.rp_subscription_id == sid
        and Invoice.objects.filter(order=o).exists()
    )


def test_verify_bad_signature_and_other_users_subscription(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    bad = c.post(
        "/api/billing/subscription/verify/",
        {
            "razorpay_payment_id": "p",
            "razorpay_subscription_id": sid,
            "razorpay_signature": sign(f"p|{sid}", "wrong"),
        },
        format="json",
    )
    assert bad.status_code == 400
    other, _ = client_for("b@x.in")
    r = other.post(
        "/api/billing/subscription/verify/",
        {"razorpay_payment_id": "p", "razorpay_subscription_id": sid, "razorpay_signature": sign(f"p|{sid}")},
        format="json",
    )
    assert r.status_code == 404 and current_plan(u).code == "free"


# ── Webhooks ────────────────────────────────────────────────────────


def test_webhook_signature_required(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    body = json.dumps(
        {
            "event": "subscription.charged",
            "payload": {"subscription": {"entity": {"id": sid}}, "payment": {"entity": captured("pay_x")}},
        }
    ).encode()
    r = APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body, "nope"),
    )
    assert r.status_code == 400 and current_plan(u).code == "free" and not WebhookEvent.objects.exists()


def test_each_charge_extends_access_and_issues_invoice(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    assert hook("subscription.activated", sid).status_code == 200
    assert hook("subscription.charged", sid, captured("pay_c1"), "evt_1").status_code == 200
    assert hook("subscription.charged", sid, captured("pay_c2"), "evt_2").status_code == 200
    assert Order.objects.filter(subscription__rp_subscription_id=sid, status="paid").count() == 2
    assert Invoice.objects.filter(order__subscription__rp_subscription_id=sid).count() == 2
    assert abs((paid_until(u) - timezone.now()) - timedelta(days=60)) < timedelta(minutes=1)
    s = Subscription.objects.get(rp_subscription_id=sid)
    assert s.status == "active" and s.method == "UPI ka•••@okhdfc" and "kavya.s" not in s.method


def test_duplicate_event_and_same_payment_are_idempotent(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    hook("subscription.charged", sid, captured("pay_d"), "evt_dup")
    r = hook("subscription.charged", sid, captured("pay_d"), "evt_dup")
    assert r.data.get("duplicate") is True
    hook("subscription.charged", sid, captured("pay_d"), "evt_other_id_same_payment")
    assert Entitlement.objects.filter(user=u).count() == 1 and Invoice.objects.count() == 1
    # the browser callback for the same payment adds nothing either
    c.post(
        "/api/billing/subscription/verify/",
        {
            "razorpay_payment_id": "pay_d",
            "razorpay_subscription_id": sid,
            "razorpay_signature": sign(f"pay_d|{sid}"),
        },
        format="json",
    )
    assert Entitlement.objects.filter(user=u).count() == 1
    # payment.captured for the same charge (it carries the order id) doesn't double-grant
    body = json.dumps(
        {"event": "payment.captured", "payload": {"payment": {"entity": captured("pay_d")}}}
    ).encode()
    APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK),
    )
    assert Entitlement.objects.filter(user=u).count() == 1


def test_uncaptured_or_foreign_payment_grants_nothing(keys, sub_gateway, renewable):
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    hook("subscription.charged", sid, {**captured("pay_f"), "status": "failed"})
    hook("subscription.charged", sid, {**captured("pay_g"), "subscription_id": "sub_someone_else"})
    assert current_plan(u).code == "free"
    assert (
        hook("subscription.charged", "sub_unknown", captured("pay_h")).data["result"]
        == "unknown_subscription"
    )


def test_pending_then_halted_gives_one_grace_and_notifies(keys, sub_gateway, renewable):
    from apps.game.models import Notification

    c, u = client_for("a@x.in")
    sid = subscribe(c)
    hook("subscription.charged", sid, captured("pay_1"))
    end = paid_until(u)
    hook("subscription.pending", sid, sub_status="pending")
    hook("subscription.halted", sid, sub_status="halted")
    graces = Entitlement.objects.filter(user=u, source="grace")
    assert graces.count() == 1 and graces[0].starts_at == end
    s = Subscription.objects.get(rp_subscription_id=sid)
    assert s.status == "halted" and s.grace_until == graces[0].ends_at
    assert Notification.objects.filter(user=u, kind="plan").count() == 2
    # a later successful charge ends the grace and stacks a full period from now
    hook("subscription.charged", sid, captured("pay_2"))
    s.refresh_from_db()
    assert s.grace_until is None and s.status == "active"


def test_cancel_keeps_access_until_period_end(keys, sub_gateway, renewable):
    calls, _ = sub_gateway
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    hook("subscription.charged", sid, captured("pay_1"))
    r = c.post("/api/billing/subscription/cancel/")
    assert r.status_code == 200 and calls["cancelled"] == [(sid, True)]
    sub = r.data["subscription"]
    assert sub["cancel_at_period_end"] and sub["next_charge_at"] is None and not sub["can_cancel"]
    hook("subscription.cancelled", sid, sub_status="cancelled")
    assert current_plan(u).code == "plus_month"  # paid time is kept
    assert c.get("/api/billing/subscription/").data["subscription"]["status"] == "cancelled"
    assert c.post("/api/billing/subscription/cancel/").status_code == 404


def test_resume_only_when_paused(keys, sub_gateway, renewable):
    calls, _ = sub_gateway
    c, _ = client_for("a@x.in")
    sid = subscribe(c)
    hook("subscription.activated", sid)
    assert c.post("/api/billing/subscription/resume/").data["code"] == "cannot_resume"
    hook("subscription.paused", sid, sub_status="paused")
    assert c.get("/api/billing/subscription/").data["subscription"]["can_resume"] is True
    r = c.post("/api/billing/subscription/resume/")
    assert r.status_code == 200 and calls["resumed"] == [sid] and r.data["subscription"]["status"] == "active"


def test_manage_endpoints_only_touch_own_subscription(keys, sub_gateway, renewable):
    calls, _ = sub_gateway
    a, _ = client_for("a@x.in")
    sid = subscribe(a)
    hook("subscription.activated", sid)
    b, _ = client_for("b@x.in")
    assert b.get("/api/billing/subscription/").data["subscription"] is None
    assert b.post("/api/billing/subscription/cancel/").status_code == 404
    assert calls["cancelled"] == []
    assert APIClient().get("/api/billing/subscription/").status_code == 401


def test_history_marks_auto_renew_charges(keys, sub_gateway, renewable):
    c, _ = client_for("a@x.in")
    sid = subscribe(c)
    hook("subscription.charged", sid, captured("pay_1"))
    h = c.get("/api/billing/history/").data
    assert h[0]["auto_renew"] is True and h[0]["invoice"]


def test_mask_method_never_keeps_full_ids():
    assert (
        mask_method({"method": "card", "card": {"network": "MasterCard", "last4": "1234"}})
        == "MasterCard •••• 1234"
    )
    assert mask_method({"method": "upi", "vpa": "9876543210@ybl"}) == "UPI 98•••@ybl"
    assert mask_method({"method": "emandate", "bank": "HDFC"}) == "Emandate HDFC"


# ── Admin ───────────────────────────────────────────────────────────


def test_admin_maps_plan_and_lists_events():
    staff, _ = client_for("admin@x.in", staff=True)
    pid = Plan.objects.get(code="plus_month").id
    assert (
        staff.patch(f"/api/admin/plans/{pid}/", {"auto_renew": True}, format="json").status_code == 400
    )  # needs a plan id first
    assert (
        staff.patch(f"/api/admin/plans/{pid}/", {"rp_plan_id": "not a plan"}, format="json").status_code
        == 400
    )
    r = staff.patch(
        f"/api/admin/plans/{pid}/", {"rp_plan_id": "plan_ABCdef123", "auto_renew": True}, format="json"
    )
    assert r.status_code == 200 and r.data["auto_renew"] is True
    free = Plan.objects.get(code="free").id
    assert (
        staff.patch(
            f"/api/admin/plans/{free}/", {"rp_plan_id": "plan_ABCdef123", "auto_renew": True}, format="json"
        ).status_code
        == 400
    )
    cfg = staff.get("/api/admin/payments/config/").data
    assert "subscription.charged" in cfg["webhook_events"] and "subscription.halted" in cfg["webhook_events"]
    assert staff.get("/api/admin/payments/subscriptions/").status_code == 200
    learner, _ = client_for("l@x.in")
    assert learner.get("/api/admin/payments/subscriptions/").status_code == 403


def test_webhook_charge_with_wrong_amount_grants_nothing(keys, sub_gateway, renewable, settings, mailoutbox):
    settings.ADMINS = [("Ops", "ops@x.in")]
    c, u = client_for("a@x.in")
    sid = subscribe(c)
    r = hook("subscription.charged", sid, captured("pay_low", amount=100), "evt_low")
    assert r.status_code == 200 and r.data["result"] == "amount_mismatch"
    assert WebhookEvent.objects.filter(event_id="evt_low").exists()  # recorded, so retries stay no-ops
    assert (
        current_plan(u).code == "free"
        and not Order.objects.filter(rp_payment_id="pay_low").exists()
        and not Invoice.objects.exists()
    )
    assert any("mismatch" in m.subject for m in mailoutbox) and "ops@x.in" in mailoutbox[-1].to
    # the correct amount still works
    hook("subscription.charged", sid, captured("pay_ok"), "evt_ok")
    assert current_plan(u).code == "plus_month"
