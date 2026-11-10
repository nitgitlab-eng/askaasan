"""Refunds from the admin console (finance role): money back through Razorpay, optionally ending the access bought.

GET  /api/admin/refunds/          ?q= &status= &page= &export=csv
POST /api/admin/refunds/          {order_id, amount_paise?, reason, end_access?}   amount defaults to what's left
"""

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.admin_paging import paged
from apps.accounts.staff import AdminSection

from . import razorpay as rp
from .models import Entitlement, Order, Refund
from .services import pay_config


def refunded(order) -> int:
    return order.refunds.exclude(status=Refund.Status.FAILED).aggregate(t=Sum("amount_paise"))["t"] or 0


def _out(r: Refund) -> dict:
    return {
        "id": r.id,
        "order_id": r.order_id,
        "email": r.order.user.email if r.order.user else "(deleted account)",
        "label": r.order.label,
        "amount_paise": r.amount_paise,
        "order_amount_paise": r.order.amount_paise,
        "reason": r.reason,
        "status": r.status,
        "error": r.error,
        "access_ended": r.access_ended,
        "rp_refund_id": r.rp_refund_id,
        "by": r.created_by.email if r.created_by else "",
        "created_at": r.created_at,
        "processed_at": r.processed_at,
    }


@api_view(["GET", "POST"])
@permission_classes([AdminSection])
def refunds(request):
    if request.method == "GET":
        qs = Refund.objects.select_related("order__user", "order__plan", "order__gift", "created_by")
        if q := str(request.query_params.get("q") or "").strip()[:80]:
            qs = qs.filter(
                Q(order__user__email__icontains=q) | Q(rp_refund_id__icontains=q) | Q(reason__icontains=q)
            )
        if (st := request.query_params.get("status")) in Refund.Status.values:
            qs = qs.filter(status=st)
        total = Refund.objects.exclude(status=Refund.Status.FAILED).aggregate(t=Sum("amount_paise"))["t"] or 0
        return paged(request, qs, _out, name="refunds", extra={"total_paise": total})
    d = request.data if isinstance(request.data, dict) else {}
    reason = " ".join(str(d.get("reason") or "").split())[:200]
    if len(reason) < 3:
        return Response({"code": "reason_required"}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        order = (
            Order.objects.select_for_update(of=("self",))
            .filter(pk=d.get("order_id"))
            .select_related("user")
            .first()
        )
        if not order or order.status != Order.Status.PAID or not order.rp_payment_id:
            return Response({"code": "order_not_refundable"}, status=status.HTTP_409_CONFLICT)
        left = order.amount_paise - refunded(order)
        amount = d.get("amount_paise", left)
        if not isinstance(amount, int) or isinstance(amount, bool) or not 0 < amount <= left:
            return Response(
                {"code": "bad_amount", "refundable_paise": left}, status=status.HTTP_400_BAD_REQUEST
            )
        cfg = pay_config()
        if not (cfg.key_id and cfg.secret):
            return Response({"code": "payments_not_configured"}, status=status.HTTP_409_CONFLICT)
        from .gifts import GiftError, void_for_refund

        try:
            gift_code, gift_expiry = void_for_refund(
                order
            )  # a used gift can't be refunded; an unused one is voided
        except GiftError as e:
            return Response({"code": str(e)}, status=status.HTTP_409_CONFLICT)
        refund = Refund.objects.create(
            order=order, amount_paise=amount, reason=reason, created_by=request.user
        )
    try:  # outside the lock: a slow gateway mustn't hold the order row
        res = rp.create_refund(cfg.keys, order.rp_payment_id, amount, {"aasan_refund": str(refund.id)})
    except rp.RazorpayError as e:
        refund.status, refund.error = Refund.Status.FAILED, f"{e.code}: {e}"[:240]
        refund.save(update_fields=["status", "error"])
        if gift_code is not None:  # no money went back: the gift code works again
            from .models import RedeemCode

            RedeemCode.objects.filter(pk=gift_code.pk, redeemed_at__isnull=True).update(
                expires_at=gift_expiry
            )
        return Response({**_out(refund), "code": "gateway_error"}, status=status.HTTP_502_BAD_GATEWAY)
    refund.rp_refund_id = str(res.get("id") or "")[:40]
    if res.get("status") == "processed":
        refund.status, refund.processed_at = Refund.Status.PROCESSED, timezone.now()
    if d.get("end_access") is True:
        n = Entitlement.objects.filter(order=order, ends_at__gt=timezone.now()).update(ends_at=timezone.now())
        refund.access_ended = bool(n)
        if n and order.user_id:
            from .family import resync_owner

            resync_owner(order.user)  # family members lose the refunded window too
    refund.save()
    return Response(_out(refund), status=status.HTTP_201_CREATED)


def handle_event(kind: str, payload: dict) -> str:
    """Webhook refund.processed / refund.failed: settle our record."""
    ent = ((payload.get("refund") or {}).get("entity")) or {}
    r = Refund.objects.filter(rp_refund_id=str(ent.get("id") or "")).first() if ent.get("id") else None
    if not r:
        return "unknown_refund"
    if kind == "refund.processed":
        r.status, r.processed_at = Refund.Status.PROCESSED, timezone.now()
    elif kind == "refund.failed":
        r.status = Refund.Status.FAILED
        r.error = str(ent.get("error_description") or "failed at the gateway")[:240]
    else:
        return "ignored"
    r.save(update_fields=["status", "processed_at", "error"])
    return r.status
