import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing.models import Entitlement, Order, Plan
from apps.billing.services import current_plan

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"


def client_for(email, staff=False):
    u = User.objects.create_user(email, "Bill#2026passwd", is_staff=staff)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def sign(msg: str | bytes, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


def pay(c, plan="plus_month", pid="pay_1"):
    r = c.post("/api/billing/checkout/", {"plan": plan}, format="json")
    assert r.status_code == 201, r.data
    oid = r.data["order_id"]
    return c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sign(f"{oid}|{pid}")},
        format="json",
    ), oid


def test_default_plans_seeded_and_free_limits_shown():
    c, _ = client_for("a@x.in")
    r = c.get("/api/billing/")
    assert r.data["plan"]["code"] == "free"
    assert r.data["usage"]["ai_courses_per_month"] == {"used": 0, "max": 2}
    assert {p["code"] for p in r.data["plans"]} >= {"free", "plus_month", "plus_year"}
    assert r.data["checkout"]["available"] is False  # no keys yet


def test_checkout_without_keys_is_unavailable():
    c, _ = client_for("a@x.in")
    assert c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").status_code == 503


def test_full_payment_flow_grants_plus(keys, gateway):
    c, u = client_for("a@x.in")
    r, oid = pay(c)
    assert r.status_code == 200 and r.data["ok"]
    assert current_plan(u).code == "plus_month"
    o = Order.objects.get(rp_order_id=oid)
    assert o.status == "paid" and o.mode == "test" and o.amount_paise == 14900
    assert c.get("/api/billing/").data["usage"]["ai_courses_per_month"]["max"] == 20


def test_amount_comes_from_server_plan_not_client(keys, gateway):
    c, _ = client_for("a@x.in")
    c.post("/api/billing/checkout/", {"plan": "plus_year", "amount": 100}, format="json")
    assert gateway[0]["orders"][-1]["amount"] == 149900


def test_bad_signature_rejected(keys, gateway):
    c, u = client_for("a@x.in")
    oid = c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").data["order_id"]
    r = c.post(
        "/api/billing/verify/",
        {
            "razorpay_order_id": oid,
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign(f"{oid}|pay_1", "wrong"),
        },
        format="json",
    )
    assert r.status_code == 400 and current_plan(u).code == "free"


def test_amount_mismatch_rejected(keys, gateway):
    c, u = client_for("a@x.in")
    gateway[1]["status"] = "captured"
    oid = c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").data["order_id"]
    gateway[1]["amount"] = 100
    r = c.post(
        "/api/billing/verify/",
        {
            "razorpay_order_id": oid,
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": sign(f"{oid}|pay_1"),
        },
        format="json",
    )
    assert r.data["code"] == "mismatch" and current_plan(u).code == "free"


def test_authorized_payment_is_captured(keys, gateway):
    gateway[1]["status"] = "authorized"
    c, _ = client_for("a@x.in")
    pay(c, pid="pay_auth")
    assert gateway[0]["captured"] == ["pay_auth"]


def test_other_users_order_not_verifiable(keys, gateway):
    a, _ = client_for("a@x.in")
    b, _ = client_for("b@x.in")
    oid = a.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").data["order_id"]
    r = b.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": "p", "razorpay_signature": sign(f"{oid}|p")},
        format="json",
    )
    assert r.status_code == 404


def test_webhook_and_callback_grant_once(keys, gateway):
    c, u = client_for("a@x.in")
    r, oid = pay(c, pid="pay_9")
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_9", "order_id": oid, "amount": 14900}}},
        }
    ).encode()
    w = APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK),
    )
    assert w.status_code == 200
    assert Entitlement.objects.filter(user=u).count() == 1


def test_webhook_alone_grants_when_tab_closed(keys, gateway):
    c, u = client_for("a@x.in")
    oid = c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json").data["order_id"]
    body = json.dumps(
        {
            "event": "order.paid",
            "payload": {"payment": {"entity": {"id": "pay_w", "order_id": oid, "amount": 14900}}},
        }
    ).encode()
    assert (
        APIClient()
        .post(
            "/api/billing/webhook/",
            body,
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK),
        )
        .status_code
        == 200
    )
    assert current_plan(u).code == "plus_month"


def test_webhook_bad_signature(keys):
    body = b'{"event":"order.paid"}'
    assert (
        APIClient()
        .post(
            "/api/billing/webhook/", body, content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="nope"
        )
        .status_code
        == 400
    )


def test_renewing_early_stacks_days(keys, gateway):
    c, u = client_for("a@x.in")
    pay(c, pid="p1")
    pay(c, pid="p2")
    ends = sorted(e.ends_at for e in Entitlement.objects.filter(user=u))
    assert abs((ends[-1] - timezone.now()) - timedelta(days=60)) < timedelta(minutes=1)


def test_free_course_limit_returns_402_then_plus_unlocks(keys, gateway):
    c, u = client_for("a@x.in")
    for _ in range(2):
        assert (
            c.post(
                "/api/learn/curriculums/", {"goal": "Learn prompt basics", "level": "beginner"}, format="json"
            ).status_code
            == 202
        )
    r = c.post("/api/learn/curriculums/", {"goal": "Learn prompt basics", "level": "beginner"}, format="json")
    assert r.status_code == 402 and r.data == {
        "code": "plan_limit",
        "limit": "ai_courses_per_month",
        "used": 2,
        "max": 2,
        "plan": "free",
    }
    pay(c)
    assert (
        c.post(
            "/api/learn/curriculums/", {"goal": "Learn prompt basics", "level": "beginner"}, format="json"
        ).status_code
        == 202
    )


def test_staff_unlimited():
    c, u = client_for("boss@x.in", staff=True)
    assert current_plan(u).code == "staff"
    assert c.get("/api/billing/").data["usage"]["documents"]["max"] is None


def test_admin_config_masks_and_blocks_live():
    a, _ = client_for("boss@x.in", staff=True)
    r = a.patch(
        "/api/admin/payments/config/", {"key_id": "rzp_test_K1", "key_secret": "supersecret99"}, format="json"
    )
    assert (
        r.status_code == 200
        and r.data["secret"] == "••••et99"
        and r.data["mode"] == "test"
        and r.data["ready"]
    )
    assert "supersecret99" not in json.dumps(r.data)
    r = a.patch("/api/admin/payments/config/", {"key_id": "rzp_live_K2"}, format="json")
    assert r.status_code == 400 and r.data["code"] == "live_not_allowed"
    r = a.patch("/api/admin/payments/config/", {"key_id": "rzp_test_OTHER"}, format="json")
    assert r.data["secret"] is None  # changing key id drops the old secret


def test_admin_endpoints_staff_only():
    c, _ = client_for("a@x.in")
    for path in ("/api/admin/payments/config/", "/api/admin/plans/", "/api/admin/payments/orders/"):
        assert c.get(path).status_code == 403


def test_admin_edits_plan_and_grants():
    a, _ = client_for("boss@x.in", staff=True)
    _, learner = client_for("l@x.in")
    p = Plan.objects.get(code="plus_month")
    assert (
        a.patch(f"/api/admin/plans/{p.id}/", {"price_paise": 19900}, format="json").data["price_paise"]
        == 19900
    )
    assert a.patch(f"/api/admin/plans/{p.id}/", {"price_paise": 50}, format="json").status_code == 400
    free = Plan.objects.get(code="free")
    assert a.patch(f"/api/admin/plans/{free.id}/", {"price_paise": 100}, format="json").status_code == 400
    assert a.patch(f"/api/admin/plans/{free.id}/", {"limits": {"bogus": 1}}, format="json").status_code == 400
    r = a.post(
        "/api/admin/payments/grant/",
        {"email": "L@X.IN", "plan": "plus_month", "days": 7, "note": "scholarship"},
        format="json",
    )
    assert r.status_code == 200 and current_plan(learner).code == "plus_month"
