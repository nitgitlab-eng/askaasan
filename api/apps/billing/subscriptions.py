"""Auto-renew with Razorpay Subscriptions.

Flow: learner picks "Auto-renew" → we create a Razorpay subscription for the plan's mapped plan_id → Razorpay Checkout
authorises it (card / UPI AutoPay mandate) → every successful charge (browser callback for the first one, then
`subscription.charged` webhooks) becomes a paid Order: access extended by the plan's period + a GST invoice.
Failed renewals (pending → halted) get one grace window and a notification; cancelling keeps access to period end.
Org seat plans stay pay-once for now."""

import logging
from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.staff import AdminSection

from . import razorpay as rp
from .models import Entitlement, Order, Plan, Subscription
from .services import grant_for_order, paid_until, pay_config

log = logging.getLogger(__name__)

GRACE_DAYS = 7  # covers Razorpay's retry window after a failed renewal
SUBSCRIPTION_EVENTS = [
    "subscription.authenticated",
    "subscription.activated",
    "subscription.charged",
    "subscription.pending",
    "subscription.halted",
    "subscription.cancelled",
    "subscription.completed",
    "subscription.paused",
    "subscription.resumed",
]
PAYMENT_EVENTS = ["payment.captured", "payment.failed", "order.paid"]


def offers_auto_renew(plan) -> bool:
    return (
        isinstance(plan, Plan)
        and plan.auto_renew
        and bool(plan.rp_plan_id)
        and plan.price_paise >= 100
        and plan.period_days > 0
    )


def total_count(plan) -> int:
    """How many cycles to authorise up front (~5 years; Razorpay needs a number). Learners can cancel any time."""
    return max(1, min(60, (5 * 365) // max(1, plan.period_days)))


def _dt(ts):
    try:
        return datetime.fromtimestamp(int(ts), tz=UTC) if ts else None
    except (TypeError, ValueError, OSError):
        return None


def mask_method(pay: dict) -> str:
    """A short, masked label for how the learner pays. Never stores a full card number or UPI id."""
    m = str(pay.get("method") or "")
    card = pay.get("card") if isinstance(pay.get("card"), dict) else {}
    if m == "card" and card:
        last4 = "".join(ch for ch in str(card.get("last4") or "") if ch.isdigit())[-4:]
        return f"{str(card.get('network') or 'Card')[:20]} •••• {last4}".strip()
    if m == "upi" and pay.get("vpa"):
        handle, _, bank = str(pay["vpa"]).partition("@")
        return f"UPI {handle[:2]}•••@{bank[:20]}" if bank else "UPI"
    if m in ("netbanking", "emandate", "nach") and pay.get("bank"):
        return f"{m.title()} {str(pay['bank'])[:12]}"
    if m == "wallet" and pay.get("wallet"):
        return f"Wallet {str(pay['wallet'])[:20]}"
    return m[:20]


def _stale(sub: Subscription, ent: dict) -> bool:
    """An event older than what we already hold (fewer payments seen): webhooks can arrive out of order."""
    try:
        return ent.get("paid_count") is not None and int(ent["paid_count"]) < sub.paid_count
    except (TypeError, ValueError):
        return False


def sync(sub: Subscription, ent: dict) -> Subscription:
    """Copy Razorpay's view of the subscription onto our row."""
    if _stale(sub, ent):
        return sub  # never let an out-of-order event roll status or dates back
    if ent.get("status"):
        sub.status = str(ent["status"])[:16]
    for f in ("current_start", "current_end", "charge_at", "ended_at"):
        if f in ent:
            setattr(sub, f, _dt(ent[f]))
    if ent.get("paid_count") is not None:
        try:
            sub.paid_count = int(ent["paid_count"])
        except (TypeError, ValueError):
            pass
    sub.save()
    return sub


def record_charge(sub: Subscription, pay: dict):
    """One successful charge → paid Order + extended access + GST invoice. Idempotent on the payment id."""
    pid, amount = str(pay.get("id") or ""), int(pay.get("amount") or 0)
    if not pid or pay.get("status") != "captured" or amount < 100 or not sub.user_id:
        return None
    if pay.get("subscription_id") and pay["subscription_id"] != sub.rp_subscription_id:
        return None
    if amount != sub.amount_paise:
        _amount_mismatch(sub, pid, amount)
        return None
    with transaction.atomic():
        sub = (
            Subscription.objects.select_for_update(of=("self",)).select_related("plan", "user").get(pk=sub.pk)
        )
        if Order.objects.filter(rp_payment_id=pid).exists():
            return None
        oid = str(pay.get("order_id") or "") or f"subpay_{pid}"
        if Order.objects.filter(rp_order_id=oid).exists():
            oid = f"subpay_{pid}"
        order = Order.objects.create(
            user=sub.user,
            plan=sub.plan,
            amount_paise=amount,
            list_paise=amount,
            rp_order_id=oid[:64],
            mode=sub.mode,
            subscription=sub,
            buyer_name=sub.buyer_name,
            buyer_gstin=sub.buyer_gstin,
            buyer_state=sub.buyer_state,
        )
        now = timezone.now()
        for g in Entitlement.objects.filter(
            user=sub.user, source="grace", ends_at__gt=now
        ):  # paid again: grace no longer needed
            g.ends_at = max(g.starts_at, now)
            g.save(update_fields=["ends_at"])
        from .family import resync_owner

        resync_owner(sub.user)  # members' copies of the grace window end with it
        sub.grace_until = None
        label = mask_method(pay)
        if label:
            sub.method = label[:60]
        sub.save(update_fields=["grace_until", "method", "updated_at"])
        return grant_for_order(order.id, pid)


def _amount_mismatch(sub: Subscription, pid: str, amount: int) -> None:
    """A charge that doesn't match what the learner signed up for never extends access; staff check it by hand
    (usually a Razorpay plan whose price differs from the Aasan plan)."""
    log.warning(
        "subscription %s charge %s amount %s != expected %s; not granting",
        sub.rp_subscription_id,
        pid,
        amount,
        sub.amount_paise,
    )
    from django.core.mail import mail_admins

    try:
        mail_admins(
            "Auto-renew charge amount mismatch",
            f"Subscription {sub.rp_subscription_id} (plan {sub.plan.code}) was charged {amount} paise for payment {pid}, "
            f"but {sub.amount_paise} paise was expected. Access was NOT extended. Check the Razorpay plan mapping, "
            "then refund or grant access manually from the admin console.",
            fail_silently=True,
        )
    except Exception:
        log.exception("mismatch alert failed")


def _notify(sub: Subscription, title: str, body: str) -> None:
    if not sub.user_id:
        return
    from .reminders import _notify as notify

    try:
        notify(sub.user, title, body)
    except Exception:  # a notification must never break webhook processing
        log.exception("subscription notice failed")


def _grace(sub: Subscription) -> None:
    """Once per failed cycle: a few extra days so a renewal hiccup doesn't cut the learner off mid-week."""
    from .services import _extend

    if sub.grace_until or not sub.user_id:
        return
    ent = _extend(
        sub.user, sub.plan, GRACE_DAYS, source="grace", note=f"auto-renew retry {sub.rp_subscription_id}"
    )
    sub.grace_until = ent.ends_at
    sub.save(update_fields=["grace_until", "updated_at"])


def _until(sub) -> str:
    end = paid_until(sub.user) if sub.user_id else None
    return f"{timezone.localtime(end):%d %b %Y}" if end else "today"


def handle_event(kind: str, payload: dict) -> str:
    """Webhook for subscription.* events (signature and duplicate checks happen before this)."""
    ent = ((payload.get("subscription") or {}).get("entity")) or {}
    pay = ((payload.get("payment") or {}).get("entity")) or {}
    sub = (
        Subscription.objects.filter(rp_subscription_id=str(ent.get("id") or ""))
        .select_related("plan", "user")
        .first()
    )
    if not sub:
        return "unknown_subscription"
    if _stale(sub, ent) and kind in ("subscription.pending", "subscription.halted"):
        return "stale"  # a later charge already succeeded: no grace period, no "payment failed" email
    sync(sub, ent)
    if kind in ("subscription.charged", "subscription.activated") and pay:
        if pay.get("status") == "captured" and int(pay.get("amount") or 0) != sub.amount_paise:
            _amount_mismatch(sub, str(pay.get("id") or ""), int(pay.get("amount") or 0))
            return "amount_mismatch"
        record_charge(sub, pay)
    elif kind in ("subscription.pending", "subscription.halted"):
        _grace(sub)
        sub.refresh_from_db()
        if kind == "subscription.pending":
            _notify(
                sub,
                f"We couldn't renew your {sub.plan.name}",
                f"Your payment didn't go through. Razorpay will try again. You keep access until {_until(sub)}.",
            )
        else:
            _notify(
                sub,
                f"Auto-renew for {sub.plan.name} has stopped",
                f"We tried a few times but couldn't collect the payment. You keep access until {_until(sub)}. "
                "Open Plans to cancel and start auto-renew again with another card or UPI app.",
            )
    elif kind == "subscription.cancelled":
        _notify(
            sub,
            f"Auto-renew for {sub.plan.name} is off",
            f"You won't be charged again. Your plan stays until {_until(sub)}.",
        )
    elif kind == "subscription.completed":
        _notify(
            sub,
            f"Your {sub.plan.name} auto-renew is complete",
            f"All planned payments are done. Your plan stays until {_until(sub)}.",
        )
    return "ok"


# ── Learner endpoints ────────────────────────────────────────────────


class SubscribeThrottle(UserRateThrottle):
    scope = "subscribe"
    rate = "20/hour"


def _live_sub(user) -> Subscription | None:
    return Subscription.objects.filter(user=user, status__in=Subscription.LIVE).select_related("plan").first()


def sub_out(sub: Subscription | None, user) -> dict:
    if not sub:
        return {"subscription": None, "access_until": paid_until(user)}
    live = sub.status in Subscription.LIVE
    return {
        "subscription": {
            "id": sub.rp_subscription_id,
            "plan": sub.plan.name,
            "plan_code": sub.plan.code,
            "status": sub.status,
            "mode": sub.mode,
            "amount_paise": sub.amount_paise,
            "period_days": sub.plan.period_days,
            "next_charge_at": None if sub.cancel_at_period_end or not live else sub.charge_at,
            "current_end": sub.current_end,
            "method": sub.method,
            "cancel_at_period_end": sub.cancel_at_period_end,
            "grace_until": sub.grace_until,
            "paid_count": sub.paid_count,
            "can_cancel": (live and not sub.cancel_at_period_end) or sub.status == "created",
            "can_resume": sub.status == "paused",
        },
        "access_until": paid_until(user),
    }


@api_view(["GET"])
def subscription(request):
    sub = (
        _live_sub(request.user)
        or Subscription.objects.filter(user=request.user)
        .exclude(status="created")
        .select_related("plan")
        .first()
    )
    return Response(sub_out(sub, request.user))


@api_view(["POST"])
@throttle_classes([SubscribeThrottle])
def subscribe(request):
    from .invoices import GSTIN, STATES

    if request.data.get("gift"):  # gifts are paid once and never auto-renew
        return Response({"code": "gift_pay_once"}, status=status.HTTP_400_BAD_REQUEST)
    plan = Plan.objects.filter(code=request.data.get("plan"), active=True).first()
    if not plan or not offers_auto_renew(plan):
        return Response({"code": "bad_plan"}, status=status.HTTP_400_BAD_REQUEST)
    if request.data.get("org"):
        return Response(
            {"code": "org_pay_once"}, status=status.HTTP_400_BAD_REQUEST
        )  # seat plans stay pay-once for now
    gstin = str(request.data.get("buyer_gstin") or "").strip().upper()
    state = str(request.data.get("buyer_state") or "").strip()
    if gstin and not GSTIN.match(gstin) or state and state not in STATES:
        return Response({"code": "bad_gst_details"}, status=status.HTTP_400_BAD_REQUEST)
    cfg = pay_config()
    if not cfg.ready:
        return Response({"code": "payments_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if _live_sub(request.user):
        return Response({"code": "already_subscribed"}, status=status.HTTP_409_CONFLICT)
    if (
        Subscription.objects.filter(
            user=request.user, created_at__gte=timezone.now() - timedelta(hours=1)
        ).count()
        >= 10
    ):
        return Response({"code": "too_many_orders"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        rs = rp.create_subscription(
            cfg.keys,
            plan.rp_plan_id,
            total_count(plan),
            notes={"user_id": str(request.user.id), "plan": plan.code},
        )
    except rp.RazorpayError as e:
        log.warning("razorpay subscription create failed: %s", e.code)
        return Response({"code": "gateway_error"}, status=status.HTTP_502_BAD_GATEWAY)
    # Abandoned earlier attempts never billed; drop them so only one auto-renew can exist.
    Subscription.objects.filter(user=request.user, status="created").update(status="expired")
    sub = Subscription.objects.create(
        user=request.user,
        plan=plan,
        rp_subscription_id=str(rs["id"])[:64],
        mode=cfg.mode,
        status=str(rs.get("status") or "created")[:16],
        amount_paise=plan.price_paise,
        buyer_name=str(request.data.get("buyer_name") or "").strip()[:160],
        buyer_gstin=gstin,
        buyer_state=state,
    )
    profile = getattr(request.user, "profile", None)
    return Response(
        {
            "subscription_id": sub.rp_subscription_id,
            "key_id": cfg.key_id,
            "name": cfg.business_name,
            "mode": cfg.mode,
            "description": plan.name,
            "amount": plan.price_paise,
            "prefill": {"email": request.user.email, "name": getattr(profile, "display_name", "") or ""},
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def subscription_verify(request):
    """Browser callback after Checkout authorises the subscription (and usually takes the first payment)."""
    pid, sid, sig = (
        str(request.data.get(k) or "")
        for k in ("razorpay_payment_id", "razorpay_subscription_id", "razorpay_signature")
    )
    sub = (
        Subscription.objects.filter(user=request.user, rp_subscription_id=sid).select_related("plan").first()
    )
    if not sub:
        return Response({"code": "subscription_not_found"}, status=status.HTTP_404_NOT_FOUND)
    cfg = pay_config()
    if not rp.valid_subscription_signature(cfg.secret, pid, sid, sig):
        return Response({"code": "bad_signature"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        sync(sub, rp.fetch_subscription(cfg.keys, sid))
        pay = rp.fetch_payment(cfg.keys, pid)
        if pay.get("status") == "captured" and int(pay.get("amount") or 0) == sub.amount_paise:
            record_charge(sub, pay)
    except rp.RazorpayError as e:  # the webhook will bring the charge in
        log.warning("razorpay subscription sync failed for %s: %s", sid, e.code)
        if sub.status == "created":
            sub.status = "authenticated"
            sub.save(update_fields=["status", "updated_at"])
    sub.refresh_from_db()
    return Response({"ok": True, "plan": sub.plan.name, **sub_out(sub, request.user)})


def _gateway_call(fn, *args):
    try:
        return fn(*args), None
    except rp.RazorpayError as e:
        log.warning("razorpay subscription call failed: %s", e.code)
        return None, Response({"code": "gateway_error"}, status=status.HTTP_502_BAD_GATEWAY)


@api_view(["POST"])
def subscription_cancel(request):
    """Turn auto-renew off. Paid time is kept: the plan stays until the current period ends."""
    sub = _live_sub(request.user) or Subscription.objects.filter(user=request.user, status="created").first()
    if not sub:
        return Response({"code": "no_subscription"}, status=status.HTTP_404_NOT_FOUND)
    if sub.cancel_at_period_end:
        return Response(sub_out(sub, request.user))
    cfg = pay_config()
    immediate = sub.status in ("created", "halted", "paused")  # nothing (more) to collect in this cycle
    ent, err = _gateway_call(rp.cancel_subscription, cfg.keys, sub.rp_subscription_id, not immediate)
    if err:
        return err
    sub.cancel_at_period_end = True
    sub.save(update_fields=["cancel_at_period_end", "updated_at"])
    sync(sub, ent or {})
    return Response(sub_out(sub, request.user))


@api_view(["POST"])
def subscription_resume(request):
    """Razorpay can resume a paused subscription; a cancellation can't be undone (start auto-renew again later)."""
    sub = _live_sub(request.user)
    if not sub:
        return Response({"code": "no_subscription"}, status=status.HTTP_404_NOT_FOUND)
    if sub.status != "paused":
        return Response({"code": "cannot_resume"}, status=status.HTTP_409_CONFLICT)
    ent, err = _gateway_call(rp.resume_subscription, pay_config().keys, sub.rp_subscription_id)
    if err:
        return err
    sync(sub, ent or {})
    return Response(sub_out(sub, request.user))


# ── Staff ────────────────────────────────────────────────────────────


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_subscriptions(request):
    qs = Subscription.objects.select_related("user", "plan").exclude(status="expired")
    return Response(
        {
            "events": SUBSCRIPTION_EVENTS + PAYMENT_EVENTS,
            "subscriptions": [
                {
                    "id": s.rp_subscription_id,
                    "email": s.user.email if s.user else "(deleted account)",
                    "plan": s.plan.name,
                    "status": s.status,
                    "mode": s.mode,
                    "amount_paise": s.amount_paise,
                    "paid_count": s.paid_count,
                    "charge_at": s.charge_at,
                    "cancel_at_period_end": s.cancel_at_period_end,
                    "created_at": s.created_at,
                }
                for s in qs[:200]
            ],
        }
    )
