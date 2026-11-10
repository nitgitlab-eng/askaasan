"""Learner billing: plan & usage, Razorpay checkout, payment verification, webhook."""

import hashlib
import json
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from . import razorpay as rp
from .family_api import family_state
from .models import LIMIT_KEYS, Gift, Order, Plan, WebhookEvent
from .services import (
    active_entitlement,
    current_plan,
    grant_for_order,
    limit_of,
    paid_until,
    pay_config,
    plan_out,
    usage,
)

log = logging.getLogger(__name__)


@api_view(["GET"])
def overview(request):
    u = request.user
    cfg = pay_config()
    plan = current_plan(u)
    ent = active_entitlement(u)
    return Response(
        {
            "plan": {**plan_out(plan), "source": ent.source if ent else None},
            "paid_until": paid_until(u),
            "usage": {k: {"used": usage(u, k), "max": limit_of(u, k)} for k in LIMIT_KEYS},
            "plans": [plan_out(p) for p in Plan.objects.filter(active=True)],
            "checkout": {"available": cfg.ready, "mode": cfg.mode},
            "family": family_state(u),
        }
    )


def _checkout_input(request, lock=False):
    """Shared by quote + checkout: plan, seats/org (seat purchase needs org admin), promo, GST buyer details."""
    from .gifts import GiftError, parse
    from .invoices import GSTIN, STATES
    from .pricing import PromoError, quote

    plan = Plan.objects.filter(code=request.data.get("plan"), active=True, price_paise__gte=100).first()
    if not plan:
        return None, Response({"code": "bad_plan"}, status=status.HTTP_400_BAD_REQUEST)
    org, seats = None, 1
    if request.data.get("org"):
        from apps.orgs.perms import require

        org = require(request.user, str(request.data["org"]), "admin").org
        try:
            seats = int(request.data.get("seats") or 0)
        except (TypeError, ValueError):
            seats = 0
        if not 1 <= seats <= 5000:
            return None, Response({"code": "bad_seats"}, status=status.HTTP_400_BAD_REQUEST)
    if request.data.get("gift") and request.data.get("auto_renew"):
        return None, Response({"code": "gift_pay_once"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        gift = parse(request.data.get("gift"), request.user, org=org)
    except GiftError as e:
        return None, Response({"code": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    gstin = str(request.data.get("buyer_gstin") or "").strip().upper()
    state = str(request.data.get("buyer_state") or "").strip()
    if gstin and not GSTIN.match(gstin) or state and state not in STATES:
        return None, Response({"code": "bad_gst_details"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        q = quote(
            request.user,
            plan,
            seats,
            str(request.data.get("promo") or ""),
            lock=lock,
            for_org=org is not None,
        )
    except PromoError as e:
        return None, Response({"code": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return {
        "q": q,
        "org": org,
        "gift": gift,
        "gstin": gstin,
        "state": state,
        "name": str(request.data.get("buyer_name") or "").strip()[:160],
    }, None


class QuoteThrottle(UserRateThrottle):
    rate = "30/hour"  # promo codes can't be dictionary-guessed


@api_view(["POST"])
@throttle_classes([QuoteThrottle])
def quote_view(request):
    inp, err = _checkout_input(request)
    return err or Response(inp["q"].out())


@api_view(["POST"])
@throttle_classes([QuoteThrottle])
@transaction.atomic  # the promo row stays locked until this order exists, so use limits hold under parallel requests
def checkout(request):
    cfg = pay_config()
    inp, err = _checkout_input(request, lock=True)
    if err:
        return err
    q, org = inp["q"], inp["org"]
    plan = q.plan
    recent = Order.objects.filter(
        user=request.user, created_at__gte=timezone.now() - timedelta(hours=1)
    ).count()
    if recent >= 10:
        return Response({"code": "too_many_orders"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    common = {
        "user": request.user,
        "plan": plan,
        "org": org,
        "seats": q.seats,
        "list_paise": q.list_paise,
        "promo": q.promo,
        "discount_paise": q.list_paise - q.total_paise if q.total_paise < q.list_paise else 0,
        "buyer_name": inp["name"],
        "buyer_gstin": inp["gstin"],
        "buyer_state": inp["state"],
    }
    if q.total_paise == 0:  # 100% promo: no gateway, grant now (no invoice for a ₹0 sale)
        import secrets

        order = Order.objects.create(
            amount_paise=0, rp_order_id=f"free_{secrets.token_hex(10)}", mode="free", **common
        )
        if inp["gift"]:
            Gift.objects.create(order=order, **inp["gift"])
        grant_for_order(order.id, "promo")
        return Response(
            {"free": True, "plan": plan.name, "gift": bool(inp["gift"])}, status=status.HTTP_201_CREATED
        )
    if not cfg.ready:
        return Response({"code": "payments_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        ro = rp.create_order(
            cfg.keys,
            q.total_paise,
            "INR",
            receipt=f"aasan-{request.user.id}-{int(timezone.now().timestamp())}",
            notes={
                "user_id": str(request.user.id),
                "plan": plan.code,
                **({"org": org.slug, "seats": str(q.seats)} if org else {}),
                **({"gift": "1"} if inp["gift"] else {}),
            },
        )
    except rp.RazorpayError as e:
        log.warning("razorpay order failed: %s", e)
        return Response({"code": "gateway_error"}, status=status.HTTP_502_BAD_GATEWAY)
    order = Order.objects.create(amount_paise=q.total_paise, rp_order_id=ro["id"], mode=cfg.mode, **common)
    if inp["gift"]:
        Gift.objects.create(order=order, **inp["gift"])
    profile = getattr(request.user, "profile", None)
    return Response(
        {
            "order_id": order.rp_order_id,
            "amount": order.amount_paise,
            "currency": "INR",
            "key_id": cfg.key_id,
            "name": cfg.business_name,
            "description": f"{plan.name} × {q.seats} seat{'' if q.seats == 1 else 's'}"
            if org
            else f"Gift: {plan.name}"
            if inp["gift"]
            else plan.name,
            "mode": cfg.mode,
            "prefill": {"email": request.user.email, "name": getattr(profile, "display_name", "") or ""},
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def verify(request):
    """Browser callback after Razorpay Checkout succeeds."""
    oid, pid, sig = (
        request.data.get(k) or "" for k in ("razorpay_order_id", "razorpay_payment_id", "razorpay_signature")
    )
    order = Order.objects.filter(user=request.user, rp_order_id=oid).select_related("plan").first()
    if not order:
        return Response({"code": "order_not_found"}, status=status.HTTP_404_NOT_FOUND)
    cfg = pay_config()
    if not rp.valid_payment_signature(cfg.secret, oid, pid, sig):
        return Response({"code": "bad_signature"}, status=status.HTTP_400_BAD_REQUEST)
    # Signature proves Razorpay authorised this payment for this order. Double-check amount, and grant only once the
    # money is captured; if Razorpay can't confirm that right now, the payment.captured webhook grants later.
    try:
        pay = rp.fetch_payment(cfg.keys, pid)
        if pay.get("order_id") != oid or int(pay.get("amount", 0)) != order.amount_paise:
            return Response({"code": "mismatch"}, status=status.HTTP_400_BAD_REQUEST)
        if pay.get("status") == "authorized":
            rp.capture_payment(cfg.keys, pid, order.amount_paise, order.currency)
        elif pay.get("status") != "captured":
            _note_pending(order, pid)
            return Response({"code": "payment_not_captured"}, status=status.HTTP_409_CONFLICT)
    except rp.RazorpayError as e:
        log.warning("razorpay fetch/capture failed for %s: %s (webhook will grant on capture)", pid, e)
        _note_pending(order, pid)
        return Response({"code": "payment_pending"}, status=status.HTTP_502_BAD_GATEWAY)
    grant = grant_for_order(order.id, pid)
    if order.workshop_run_id:
        if grant is None:  # paid, but the seat couldn't be given (run_full, run_closed, …): staff refund it
            order.refresh_from_db(fields=["error"])
            return Response({"code": order.error or "run_full"}, status=status.HTTP_409_CONFLICT)
        return Response(
            {"ok": True, "plan": None, "workshop_run": order.workshop_run_id, "ends_at": None, "org": None}
        )
    if grant is None:
        return Response({"code": "promo_used_up"}, status=status.HTTP_409_CONFLICT)
    if isinstance(grant, Gift):
        return Response(
            {"ok": True, "plan": order.plan.name, "ends_at": None, "org": None, "gift": True},
        )
    return Response(
        {
            "ok": True,
            "plan": order.plan.name,
            "ends_at": grant.ends_at,
            "org": order.org.slug if order.org_id else None,
        }
    )


def _note_pending(order, pid: str) -> None:
    """A signed payment that isn't captured yet: remember its id (the webhook grants on capture), so a workshop seat
    can show as "payment pending"."""
    if order.status == Order.Status.CREATED and not order.rp_payment_id:
        Order.objects.filter(pk=order.pk, status=Order.Status.CREATED).update(rp_payment_id=pid[:64])


@api_view(["POST"])
def failed(request):
    """Checkout reported a failure; keep the reason for the user's history."""
    order = Order.objects.filter(
        user=request.user,
        rp_order_id=request.data.get("razorpay_order_id") or "",
        status=Order.Status.CREATED,
    ).first()
    if order:
        order.status, order.error = Order.Status.FAILED, str(request.data.get("reason") or "")[:240]
        order.save(update_fields=["status", "error"])
    return Response({"ok": True})


@api_view(["GET"])
def history(request):
    return Response(
        [
            {
                "id": o.id,
                "plan": o.label,
                "workshop_run": o.workshop_run_id,
                "amount_paise": o.amount_paise,
                "status": o.status,
                "mode": o.mode,
                "auto_renew": bool(o.subscription_id),
                "created_at": o.created_at,
                "paid_at": o.paid_at,
                "payment_id": o.rp_payment_id,
                "order_id": o.rp_order_id,
                "org": o.org.name if o.org_id else None,
                "seats": o.seats,
                "discount_paise": o.discount_paise,
                "invoice": o.invoice.number if hasattr(o, "invoice") else None,
                "gift": _gift_out(o),
            }
            for o in Order.objects.filter(user=request.user).select_related(
                "plan", "org", "invoice", "workshop_run__workshop", "gift__redeem_code"
            )[:50]
        ]
    )


def _gift_out(o) -> dict | None:
    if not o.is_gift:
        return None
    g, rc = o.gift, o.gift.redeem_code
    return {
        "recipient_email": g.recipient_email,
        "sent": bool(g.sent_at),
        "claimed": bool(g.claimed_at),
        # The buyer can share the code themselves only if our email didn't go out.
        "code": rc.code if rc and not g.sent_at and not g.claimed_at else None,
    }


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
def webhook(request):
    """Razorpay → us. Backs up the browser callback (tab closed, network drop). Configure in Razorpay Dashboard → Webhooks."""
    cfg = pay_config()
    body = request.body
    if not rp.valid_webhook_signature(
        cfg.webhook_secret, body, request.headers.get("X-Razorpay-Signature", "")
    ):
        return Response({"code": "bad_signature"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        event = json.loads(body)
    except ValueError:
        return Response(status=status.HTTP_400_BAD_REQUEST)
    if not isinstance(event, dict):
        return Response(status=status.HTTP_400_BAD_REQUEST)
    kind = str(event.get("event") or "")
    # Idempotent: Razorpay retries and may deliver twice. Recorded in the same transaction as the work, so a crash retries.
    # The event-id header isn't signed, so the signed body's hash is recorded too: a replayed body is a duplicate
    # whatever header it comes with.
    ids = {
        "sha256:" + hashlib.sha256(body).hexdigest()[:72],
        (request.headers.get("X-Razorpay-Event-Id") or "")[:80],
    } - {""}
    with transaction.atomic():
        try:
            with transaction.atomic():
                WebhookEvent.objects.bulk_create(
                    [WebhookEvent(event_id=i, kind=kind[:48]) for i in sorted(ids)]
                )
        except IntegrityError:
            return Response({"ok": True, "duplicate": True})
        return _handle_webhook(kind, event)


def _handle_webhook(kind: str, event: dict):
    payload = event.get("payload") or {}
    if kind.startswith("subscription.") or payload.get("subscription"):
        from .subscriptions import handle_event

        return Response({"ok": True, "result": handle_event(kind, payload)})
    if kind.startswith("refund."):
        from .refunds import handle_event

        return Response({"ok": True, "result": handle_event(kind, payload)})
    pay = ((payload.get("payment") or {}).get("entity")) or {}
    order = Order.objects.filter(rp_order_id=pay.get("order_id") or "").first()
    if not order:
        return Response({"ok": True, "ignored": "unknown_order"})
    if kind in ("payment.captured", "order.paid") and int(pay.get("amount", 0)) == order.amount_paise:
        grant_for_order(order.id, pay.get("id", ""))
    elif kind == "payment.failed" and order.status == Order.Status.CREATED:
        order.status, order.error = Order.Status.FAILED, (pay.get("error_description") or "")[:240]
        order.save(update_fields=["status", "error"])
    return Response({"ok": True})
