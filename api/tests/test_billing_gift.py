"""Gift a plan: checkout validation, the code created on verify / webhook / reconcile exactly once, the email, redeem as
source="gift" with the buyer told, expiry, refunds before and after redemption, a 100% promo gift, invoice and
history. Razorpay is always the conftest fake (`keys`/`gateway`)."""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import StaffRole, User
from apps.billing.models import Entitlement, Gift, Invoice, Order, PromoCode, RedeemCode
from apps.billing.services import current_plan, grant_for_order
from apps.game.models import Notification
from apps.orgs.models import Membership, Organization

pytestmark = pytest.mark.django_db
SECRET, HOOK = "test_secret_abc123", "whsec_xyz789"
PW = "Gift#Plan2026"
GIFT = {"recipient_email": "Paati@Home.in", "message": "Happy birthday, learn Tamil with me!"}


def client_for(email, roles=None):
    u = User.objects.create_user(email, PW)
    if roles is not None:
        u.is_staff = True
        u.save()
        StaffRole.objects.create(user=u, roles=roles)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def sign(msg, secret=SECRET):
    return hmac.new(
        secret.encode(), msg if isinstance(msg, bytes) else msg.encode(), hashlib.sha256
    ).hexdigest()


def checkout(c, **extra):
    return c.post("/api/billing/checkout/", {"plan": "plus_year", "gift": GIFT, **extra}, format="json")


def verify(c, oid, pid="pay_g1"):
    return c.post(
        "/api/billing/verify/",
        {"razorpay_order_id": oid, "razorpay_payment_id": pid, "razorpay_signature": sign(f"{oid}|{pid}")},
        format="json",
    )


@pytest.fixture
def bought(keys, gateway, django_capture_on_commit_callbacks):
    c, u = client_for("magan@home.in")
    r = checkout(c)
    assert r.status_code == 201 and r.data["description"] == "Gift: Aasan Plus · Yearly"
    mail.outbox.clear()
    with django_capture_on_commit_callbacks(execute=True):
        v = verify(c, r.data["order_id"])
    assert v.status_code == 200, v.data
    return c, u, v, Order.objects.get(rp_order_id=r.data["order_id"])


def webhook(event, order, pid="pay_g1"):
    body = json.dumps(
        {
            "event": event,
            "payload": {
                "payment": {
                    "entity": {"id": pid, "order_id": order.rp_order_id, "amount": order.amount_paise}
                }
            },
        }
    ).encode()
    return APIClient().post(
        "/api/billing/webhook/",
        body,
        content_type="application/json",
        HTTP_X_RAZORPAY_SIGNATURE=sign(body, HOOK),
    )


# ── checkout ────────────────────────────────────────────────────────


def test_gift_checkout_validation(keys, gateway, sub_gateway):
    c, u = client_for("magan@home.in")
    assert checkout(c, gift={"recipient_email": "MAGAN@home.in"}).data["code"] == "gift_self"
    assert checkout(c, gift={"recipient_email": "not-an-email"}).data["code"] == "bad_gift_email"
    assert checkout(c, gift="paati").data["code"] == "bad_gift"
    assert checkout(c, auto_renew=True).data["code"] == "gift_pay_once"
    org = Organization.objects.create(name="Vidya School", slug="vidya", kind="school")
    Membership.objects.create(org=org, user=u, role="admin")
    assert checkout(c, org="vidya", seats=3).data["code"] == "gift_org"
    r = c.post("/api/billing/subscribe/", {"plan": "plus_month", "gift": GIFT}, format="json")
    assert r.status_code == 400 and r.data["code"] == "gift_pay_once"
    long = checkout(c, gift={**GIFT, "message": "x" * 500})
    assert long.status_code == 201
    gift = Gift.objects.get(order__rp_order_id=long.data["order_id"])
    assert len(gift.message) == 300 and gift.recipient_email == "paati@home.in"
    assert gateway[0]["orders"][-1]["notes"]["gift"] == "1"


# ── capture → code ─────────────────────────────────────────────────


def test_verify_creates_one_code_and_emails_it(bought):
    c, u, v, order = bought
    assert v.data == {"ok": True, "plan": "Aasan Plus · Yearly", "ends_at": None, "org": None, "gift": True}
    gift = Gift.objects.get(order=order)
    rc = gift.redeem_code
    assert rc.batch == "gift" and rc.plan.code == "plus_year" and rc.days == 365 and not rc.redeemed_at
    assert timedelta(days=364) < rc.expires_at - timezone.now() <= timedelta(days=365)
    assert (
        current_plan(u).code == "free" and not Entitlement.objects.filter(user=u).exists()
    )  # the buyer gets none
    sent = [m for m in mail.outbox if m.to == ["paati@home.in"]]
    assert len(sent) == 1 and sent[0].subject == "You've been gifted an Aasan plan"
    assert rc.code in sent[0].body and f"/plans?code={rc.code}" in sent[0].body
    assert GIFT["message"] in sent[0].body and GIFT["message"] not in sent[0].subject
    assert gift.__class__.objects.get(pk=gift.pk).sent_at is not None
    assert any(m.to == ["magan@home.in"] and "gift" in m.body for m in mail.outbox)  # buyer's receipt
    inv = Invoice.objects.get(order=order)
    assert (
        inv.lines[0]["description"] == "Gift: Aasan Plus · Yearly (365 days)"
        and inv.buyer["email"] == "magan@home.in"
    )
    assert order.label == "Gift: Aasan Plus · Yearly"
    h = c.get("/api/billing/history/").data[0]
    assert h["plan"] == "Gift: Aasan Plus · Yearly" and h["gift"]["recipient_email"] == "paati@home.in"
    assert h["gift"]["sent"] is True and h["gift"]["code"] is None


def test_duplicate_webhook_and_reconcile_are_idempotent(bought, monkeypatch):
    from apps.billing import razorpay as rp
    from apps.billing.reconcile import reconcile_orders

    _, _, _, order = bought
    assert webhook("payment.captured", order).data == {"ok": True}
    assert webhook("order.paid", order, pid="pay_g1").status_code == 200
    assert isinstance(grant_for_order(order.id, "pay_g1"), Gift)
    monkeypatch.setattr(rp, "fetch_order_payments", lambda k, oid: [])
    reconcile_orders()
    assert RedeemCode.objects.filter(batch="gift").count() == 1


def test_webhook_alone_fulfils(keys, gateway, django_capture_on_commit_callbacks):
    c, _ = client_for("magan@home.in")
    oid = checkout(c).data["order_id"]
    order = Order.objects.get(rp_order_id=oid)
    with django_capture_on_commit_callbacks(execute=True):
        webhook("payment.captured", order, pid="pay_w")
    assert Gift.objects.get(order=order).redeem_code.batch == "gift"
    assert verify(c, oid, pid="pay_w").data["gift"] is True  # the callback after the webhook: same gift
    assert RedeemCode.objects.count() == 1


def test_reconcile_fulfils_a_missed_gift(keys, gateway, monkeypatch):
    from apps.billing import razorpay as rp
    from apps.billing.reconcile import reconcile_orders

    c, _ = client_for("magan@home.in")
    oid = checkout(c).data["order_id"]
    order = Order.objects.get(rp_order_id=oid)
    Order.objects.filter(pk=order.pk).update(created_at=timezone.now() - timedelta(minutes=10))
    monkeypatch.setattr(
        rp,
        "fetch_order_payments",
        lambda k, o: [{"id": "pay_r", "status": "captured", "order_id": oid, "amount": order.amount_paise}],
    )
    assert reconcile_orders()["granted"] == 1
    reconcile_orders()
    assert RedeemCode.objects.filter(batch="gift").count() == 1


def test_mail_failure_shows_the_code_to_the_buyer(
    keys, gateway, monkeypatch, django_capture_on_commit_callbacks
):
    from apps.billing import gifts

    def boom(*a, **k):
        raise OSError("smtp down")

    monkeypatch.setattr("django.core.mail.send_mail", boom)
    c, _ = client_for("magan@home.in")
    oid = checkout(c).data["order_id"]
    with django_capture_on_commit_callbacks(execute=True):
        verify(c, oid)
    rc = RedeemCode.objects.get()
    assert c.get("/api/billing/history/").data[0]["gift"]["code"] == rc.code
    assert gifts.Gift.objects.get().sent_at is None


# ── redeem ──────────────────────────────────────────────────────────


def test_recipient_redeems_and_the_buyer_is_told(bought, django_capture_on_commit_callbacks):
    _, buyer, _, order = bought
    code = Gift.objects.get(order=order).redeem_code.code
    p, pu = client_for("paati@home.in")
    with django_capture_on_commit_callbacks(execute=True):
        r = p.post("/api/billing/redeem/", {"code": code}, format="json")
    assert r.status_code == 200 and r.data["plan"] == "Aasan Plus · Yearly"
    ent = Entitlement.objects.get(user=pu)
    assert ent.source == "gift" and current_plan(pu).code == "plus_year"
    assert Gift.objects.get(order=order).claimed_at is not None
    assert Notification.objects.filter(user=buyer, title="Your gift is being used").exists()
    assert p.post("/api/billing/redeem/", {"code": code}, format="json").data["code"] == "code_used"


def test_expired_gift_code(bought):
    _, _, _, order = bought
    rc = Gift.objects.get(order=order).redeem_code
    RedeemCode.objects.filter(pk=rc.pk).update(expires_at=timezone.now() - timedelta(days=1))
    p, _ = client_for("paati@home.in")
    assert p.post("/api/billing/redeem/", {"code": rc.code}, format="json").data["code"] == "code_expired"


# ── refunds ─────────────────────────────────────────────────────────


@pytest.fixture
def refund_gateway(monkeypatch):
    from apps.billing import razorpay as rp

    sent = []
    monkeypatch.setattr(
        rp,
        "create_refund",
        lambda k, pid, amt, notes: sent.append(amt) or {"id": "rfnd_1", "status": "pending"},
    )
    return sent


def test_refund_before_redemption_voids_the_code(bought, refund_gateway):
    _, _, _, order = bought
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    r = fin.post("/api/admin/refunds/", {"order_id": order.id, "reason": "Changed mind"}, format="json")
    assert r.status_code == 201 and refund_gateway == [149900]
    code = Gift.objects.get(order=order).redeem_code.code
    p, _ = client_for("paati@home.in")
    assert p.post("/api/billing/redeem/", {"code": code}, format="json").data["code"] == "code_expired"
    a = fin.get("/api/admin/gifts/").data["results"][0]
    assert a["status"] == "void"


def test_failed_refund_restores_the_code(bought, monkeypatch):
    from apps.billing import razorpay as rp

    def boom(*a):
        raise rp.RazorpayError("api_error", "nope")

    monkeypatch.setattr(rp, "create_refund", boom)
    _, _, _, order = bought
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    assert (
        fin.post("/api/admin/refunds/", {"order_id": order.id, "reason": "Try"}, format="json").status_code
        == 502
    )
    rc = Gift.objects.get(order=order).redeem_code
    rc.refresh_from_db()
    assert rc.expires_at > timezone.now() + timedelta(days=300)


def test_refund_after_redemption_is_refused(bought, refund_gateway):
    _, _, _, order = bought
    p, _ = client_for("paati@home.in")
    p.post("/api/billing/redeem/", {"code": Gift.objects.get(order=order).redeem_code.code}, format="json")
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    r = fin.post("/api/admin/refunds/", {"order_id": order.id, "reason": "Too late"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "gift_redeemed" and refund_gateway == []


# ── free gifts and admin ────────────────────────────────────────────


def test_full_promo_gift_needs_no_gateway(django_capture_on_commit_callbacks):
    PromoCode.objects.create(code="GIFTFREE", kind="percent", value=100)
    c, _ = client_for("magan@home.in")
    with django_capture_on_commit_callbacks(execute=True):
        r = checkout(c, promo="GIFTFREE")
    assert r.status_code == 201 and r.data == {"free": True, "plan": "Aasan Plus · Yearly", "gift": True}
    gift = Gift.objects.get()
    assert gift.redeem_code and gift.sent_at and not Invoice.objects.exists()


def test_admin_gifts_list_and_csv(bought):
    fin, _ = client_for("fin@aasan.in", roles=["finance"])
    r = fin.get("/api/admin/gifts/?q=paati")
    row = r.data["results"][0]
    assert r.data["count"] == 1 and row["buyer"] == "magan@home.in" and row["status"] == "sent"
    assert len(row["code_last4"]) == 4 and row["plan"] == "Aasan Plus · Yearly"
    csv = fin.get("/api/admin/gifts/?export=csv")
    assert csv["Content-Type"].startswith("text/csv") and b"paati@home.in" in csv.content
