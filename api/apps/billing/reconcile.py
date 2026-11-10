"""Payment reconciliation: a backstop for the browser callback and the webhook.

If a grant fails after Razorpay captured the money (a transient error during verify) and the webhook can't reach us
(local and dev hosts), the order would sit "created" with no seat or plan. Every 10 minutes (Celery beat) this asks
Razorpay for the payments of each such order and, for a captured one with the right amount, runs the same idempotent
grant_for_order as verify and the webhook. Only Razorpay's own API response is trusted: nothing from the browser."""

import logging
from datetime import timedelta

from django.utils import timezone

from . import razorpay as rp
from .models import Order
from .services import PROMO_USED_UP, grant_for_order, pay_config

log = logging.getLogger(__name__)

MIN_AGE = timedelta(minutes=5)  # leave fresh checkouts to the callback and the webhook
MAX_AGE = timedelta(days=3)  # an order still unpaid after this is marked failed
BATCH = 200


def _captured(order, payments) -> str | None:
    """The id of a captured payment for exactly this order and amount, else None."""
    for p in payments:
        if (
            p.get("status") == "captured"
            and p.get("order_id") == order.rp_order_id
            and str(p.get("currency") or order.currency) == order.currency
        ):
            try:
                amount = int(p.get("amount", -1))
            except (TypeError, ValueError):
                continue
            if amount == order.amount_paise and p.get("id"):
                return str(p["id"])[:64]
    return None


def reconcile_orders() -> dict:
    """Workshop-seat and plan orders (personal or org) still "created" between MIN_AGE and MAX_AGE old: grant the
    captured ones, leave authorized ones (verify or the webhook captures them), and mark orders past MAX_AGE failed
    once Razorpay confirms nothing was captured. Orders whose promo ran out are staff's to refund: skipped."""
    out = {"checked": 0, "granted": 0, "authorized": 0, "expired": 0, "errors": 0}
    cfg = pay_config()
    if not cfg.ready:
        return out
    now = timezone.now()
    rows = (
        Order.objects.filter(
            status=Order.Status.CREATED,
            mode=cfg.mode,  # an order made with test keys can't be looked up with live ones (and vice versa)
            subscription__isnull=True,
            created_at__lt=now - MIN_AGE,
            rp_order_id__startswith="order_",
        )
        .exclude(error=PROMO_USED_UP)
        .exclude(plan__isnull=True, workshop_run__isnull=True)
        .order_by("created_at")[:BATCH]
    )
    for order in rows:
        out["checked"] += 1
        try:
            payments = rp.fetch_order_payments(cfg.keys, order.rp_order_id)
        except rp.RazorpayError as e:
            log.warning("reconcile: razorpay lookup failed for %s: %s", order.rp_order_id, e)
            out["errors"] += 1
            continue
        if pid := _captured(order, payments):
            try:
                # Seat or plan; a refused seat (run full or closed) keeps its refund flag and staff email.
                grant_for_order(order.id, pid)
            except Exception:
                log.exception("reconcile: grant failed for order %s", order.rp_order_id)
                out["errors"] += 1
                continue
            log.info("reconcile: granted order %s (payment %s)", order.rp_order_id, pid)
            out["granted"] += 1
        elif any(p.get("status") == "authorized" for p in payments):
            out["authorized"] += 1  # money held, not captured yet: never granted here
        elif order.created_at < now - MAX_AGE:
            n = Order.objects.filter(pk=order.pk, status=Order.Status.CREATED).update(
                status=Order.Status.FAILED, error="expired"
            )
            out["expired"] += n
    return out
