"""Payment reconciliation (beat task): orders Razorpay captured but we never granted get their seat or plan, once,
from Razorpay's own API answer only (test doubles here; nothing calls the real gateway)."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.conf import settings as dj_settings
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.billing import razorpay as rp
from apps.billing import tasks
from apps.billing.models import Entitlement, Invoice, Order
from apps.billing.reconcile import reconcile_orders
from apps.game.models import Notification
from apps.workshops.content import seed
from apps.workshops.models import Workshop, WorkshopEnrollment, WorkshopRun

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"


@pytest.fixture(autouse=True)
def _seeded(db, settings):
    seed()
    settings.ADMINS = [("Ops", "ops@example.com")]


@pytest.fixture
def payments(monkeypatch, gateway):
    """Razorpay GET /orders/<id>/payments double: state["items"] (by order id) or state["error"]."""
    state = {"items": {}, "error": None, "asked": []}

    def fetch_order_payments(keys, order_id):
        assert keys.key_id == "rzp_test_ABC123" and keys.secret == SECRET
        state["asked"].append(order_id)
        if state["error"]:
            raise rp.RazorpayError("network", "down")
        return list(state["items"].get(order_id, []))

    monkeypatch.setattr(rp, "fetch_order_payments", fetch_order_payments)
    return state


def _client(email):
    u = User.objects.create_user(email, "Work#2026passwd", email_verified=True)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def _run(**kw):
    return WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug="quick-check"),
        audience="public",
        starts_at=timezone.now() + timedelta(days=2),
        status="scheduled",
        **kw,
    )


def _sign(msg, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


def _age(oid, **kw):
    Order.objects.filter(rp_order_id=oid).update(created_at=timezone.now() - timedelta(**kw))


def _seat_order(c, run, age_minutes=10):
    oid = c.post(f"/api/workshops/runs/{run.id}/checkout/", {}, format="json").data["order_id"]
    _age(oid, minutes=age_minutes)
    return oid


def _pay(oid, amount, status="captured", pid="pay_r1", **extra):
    return {"id": pid, "order_id": oid, "amount": amount, "currency": "INR", "status": status, **extra}


def test_beat_runs_reconciliation_every_10_minutes():
    entry = dj_settings.CELERY_BEAT_SCHEDULE["payment-reconcile"]
    assert entry == {"task": "apps.billing.tasks.reconcile_payments", "schedule": 600}


def test_captured_seat_is_granted_once_and_verify_and_webhook_stay_idempotent(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, u = _client("a@example.com")
    oid = _seat_order(c, run)
    payments["items"][oid] = [_pay(oid, 9900, "failed", pid="pay_f"), _pay(oid, 9900)]

    out = tasks.reconcile_payments()
    assert out["granted"] == 1 and out["checked"] == 1
    order = Order.objects.get(rp_order_id=oid)
    assert order.status == "paid" and order.rp_payment_id == "pay_r1"
    assert WorkshopEnrollment.objects.get(user=u, run=run).order == order
    assert Invoice.objects.filter(order=order).count() == 1

    assert reconcile_orders()["checked"] == 0  # paid orders are no longer looked up
    # The browser callback and the webhook landing late change nothing.
    v = c.post(
        "/api/billing/verify/",
        {
            "razorpay_order_id": oid,
            "razorpay_payment_id": "pay_r1",
            "razorpay_signature": _sign(f"{oid}|pay_r1"),
        },
        format="json",
    )
    assert v.status_code == 200
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {"payment": {"entity": {"id": "pay_r1", "order_id": oid, "amount": 9900}}},
        }
    ).encode()
    hook = APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=_sign(body, HOOK),
    )
    assert hook.status_code == 200
    assert WorkshopEnrollment.objects.filter(user=u, run=run).count() == 1
    assert Invoice.objects.filter(order=order).count() == 1
    assert sum("payment received" in m.subject.lower() for m in mail.outbox) == 1


def test_verify_first_then_reconcile_does_nothing(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, u = _client("a@example.com")
    oid = _seat_order(c, run)
    v = c.post(
        "/api/billing/verify/",
        {
            "razorpay_order_id": oid,
            "razorpay_payment_id": "pay_1",
            "razorpay_signature": _sign(f"{oid}|pay_1"),
        },
        format="json",
    )
    assert v.status_code == 200
    payments["items"][oid] = [_pay(oid, 9900, pid="pay_1")]
    assert reconcile_orders()["granted"] == 0 and not payments["asked"]
    assert WorkshopEnrollment.objects.filter(user=u).count() == 1


def test_captured_plan_order_grants_the_plan(keys, gateway, payments):
    c, u = _client("p@example.com")
    r = c.post("/api/billing/checkout/", {"plan": "plus_month"}, format="json")
    assert r.status_code == 201, r.data
    oid = r.data["order_id"]
    _age(oid, minutes=30)
    amount = Order.objects.get(rp_order_id=oid).amount_paise
    payments["items"][oid] = [_pay(oid, amount)]
    assert reconcile_orders()["granted"] == 1
    ent = Entitlement.objects.get(order__rp_order_id=oid)
    assert ent.user == u and ent.plan.code == "plus_month"
    assert reconcile_orders()["granted"] == 0
    assert Entitlement.objects.filter(user=u).count() == 1


def test_authorized_only_is_left_alone(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, u = _client("a@example.com")
    oid = _seat_order(c, run)
    payments["items"][oid] = [_pay(oid, 9900, "authorized")]
    out = reconcile_orders()
    assert out["authorized"] == 1 and out["granted"] == 0
    assert Order.objects.get(rp_order_id=oid).status == "created"
    assert not WorkshopEnrollment.objects.filter(user=u).exists()
    assert not gateway[0]["captured"]  # never captured from here


def test_wrong_amount_other_order_and_fresh_orders_are_not_granted(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, u = _client("a@example.com")
    oid = _seat_order(c, run)
    payments["items"][oid] = [
        _pay(oid, 100),  # wrong amount
        _pay("order_someone_else", 9900, pid="pay_x"),  # Razorpay says it belongs to another order
        _pay(oid, 9900, pid="pay_usd", currency="USD"),
    ]
    assert reconcile_orders()["granted"] == 0
    c2, u2 = _client("b@example.com")
    fresh = _seat_order(c2, run, age_minutes=1)  # still within the callback's window
    payments["items"][fresh] = [_pay(fresh, 9900, pid="pay_fresh")]
    reconcile_orders()
    assert fresh not in payments["asked"]
    assert not WorkshopEnrollment.objects.filter(user__in=[u, u2]).exists()


def test_run_full_keeps_the_refund_path(keys, gateway, payments, django_capture_on_commit_callbacks):
    run = _run(price_paise=9900, capacity=1)
    c, u = _client("a@example.com")
    oid = _seat_order(c, run)
    _, other = _client("b@example.com")
    WorkshopEnrollment.objects.create(run=run, user=other)  # the last seat went while a was paying
    payments["items"][oid] = [_pay(oid, 9900)]
    with django_capture_on_commit_callbacks(execute=True):
        assert reconcile_orders()["granted"] == 1
    order = Order.objects.get(rp_order_id=oid)
    assert order.status == "paid" and order.error == "run_full"
    assert not WorkshopEnrollment.objects.filter(user=u).exists()
    assert not Invoice.objects.filter(order=order).exists()
    assert any("ops@example.com" in m.to and oid in m.body for m in mail.outbox)
    assert Notification.objects.filter(user=u, kind="workshop").count() == 1
    with django_capture_on_commit_callbacks(execute=True):
        reconcile_orders()
    assert sum("ops@example.com" in m.to for m in mail.outbox) == 1  # staff alerted once


def test_old_unpaid_orders_are_marked_failed(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, u = _client("a@example.com")
    stale = _seat_order(c, run)
    _age(stale, days=3, minutes=1)
    c2, _ = _client("b@example.com")
    late = _seat_order(c2, run)
    _age(late, days=4)
    payments["items"][late] = [_pay(late, 9900, pid="pay_late")]  # captured late: granted, not expired
    out = reconcile_orders()
    assert out["expired"] == 1 and out["granted"] == 1
    o = Order.objects.get(rp_order_id=stale)
    assert o.status == "failed" and o.error == "expired"
    assert Order.objects.get(rp_order_id=late).status == "paid"


def test_gateway_errors_change_nothing(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, _ = _client("a@example.com")
    oid = _seat_order(c, run)
    _age(oid, days=5)
    payments["error"] = True
    out = reconcile_orders()
    assert out["errors"] == 1 and out["expired"] == 0
    assert Order.objects.get(rp_order_id=oid).status == "created"  # not failed on a lookup error


def test_skips_without_keys_and_promo_used_up(keys, gateway, payments):
    run = _run(price_paise=9900)
    c, _ = _client("a@example.com")
    oid = _seat_order(c, run)
    Order.objects.filter(rp_order_id=oid).update(error="promo_used_up")
    payments["items"][oid] = [_pay(oid, 9900)]
    assert reconcile_orders()["checked"] == 0  # staff refund or grant those by hand
    from apps.billing.models import PaymentConfig

    PaymentConfig.objects.filter(pk=1).update(enabled=False)
    Order.objects.filter(rp_order_id=oid).update(error="")
    assert reconcile_orders() == {"checked": 0, "granted": 0, "authorized": 0, "expired": 0, "errors": 0}


def test_fetch_order_payments_reads_items(monkeypatch):
    seen = {}

    def fake_call(keys, method, path, json=None, params=None):
        seen["req"] = (method, path)
        return {"entity": "collection", "items": [{"id": "pay_1"}, "junk"]}

    monkeypatch.setattr(rp, "_call", fake_call)
    assert rp.fetch_order_payments(rp.Keys("rzp_test_x", "s"), "order_9") == [{"id": "pay_1"}]
    assert seen["req"] == ("GET", "/orders/order_9/payments")
