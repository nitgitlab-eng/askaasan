"""P8: redeem codes, invoices, org seats; admin promo + redeem-code management."""

import csv
import io
import secrets

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts import counters
from apps.accounts.staff import AdminSection
from apps.orgs.csvsafe import csv_safe

from .models import Invoice, Order, OrgSubscription, Plan, PromoCode, RedeemCode
from .services import _extend, assign_seats, seats_total

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
REDEEM_FAILS_PER_HOUR = 10


def _new_code(n=12) -> str:
    raw = "".join(secrets.choice(ALPHABET) for _ in range(n))
    return "-".join(raw[i : i + 4] for i in range(0, n, 4))


# ── Learner: redeem a prepaid code ───────────────────────────────────


@api_view(["POST"])
def redeem(request):
    key = f"redeem-fail:{request.user.id}"
    if counters.count(key) >= REDEEM_FAILS_PER_HOUR:  # stops guessing codes
        return Response({"code": "too_many_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    code = str(request.data.get("code") or "").strip().upper().replace(" ", "")
    if len(code) == 12 and "-" not in code:
        code = "-".join(code[i : i + 4] for i in range(0, 12, 4))
    with transaction.atomic():
        rc = (
            RedeemCode.objects.select_for_update(of=("self",))
            .select_related("plan")
            .filter(code=code)
            .first()
        )
        if not rc or rc.redeemed_at or (rc.expires_at and rc.expires_at < timezone.now()):
            counters.bump(key, 3600)
            reason = (
                "code_used"
                if rc and rc.redeemed_at
                else "code_expired"
                if rc and rc.expires_at and rc.expires_at < timezone.now()
                else "code_invalid"
            )
            return Response({"code": reason}, status=status.HTTP_400_BAD_REQUEST)
        is_gift = rc.batch == "gift" and hasattr(rc, "gift")
        ent = _extend(
            request.user, rc.plan, rc.days, source="gift" if is_gift else "redeem", note=f"code {rc.code}"
        )
        rc.redeemed_by, rc.redeemed_at = request.user, timezone.now()
        rc.save(update_fields=["redeemed_by", "redeemed_at"])
        if is_gift:
            from .gifts import on_redeemed

            on_redeemed(rc, request.user)
        if rc.org_id:  # a school's code also makes the learner a member
            from apps.orgs.api import _join

            _join(request.user, rc.org, "learner")
    return Response({"plan": rc.plan.name, "ends_at": ent.ends_at, "org": rc.org.slug if rc.org_id else None})


# ── Invoices ─────────────────────────────────────────────────────────


def _can_see(user, order) -> bool:
    if order.user_id == user.id or user.is_staff:
        return True
    if order.org_id:
        from apps.orgs.models import Membership

        return Membership.objects.filter(org_id=order.org_id, user=user, role__in=["admin", "owner"]).exists()
    return False


@api_view(["GET"])
def invoice_pdf(request, number):
    from .invoices import render_pdf

    inv = get_object_or_404(
        Invoice.objects.select_related("order__plan", "order__org"), number=number.replace("_", "/")
    )
    if not _can_see(request.user, inv.order):
        return Response(status=status.HTTP_404_NOT_FOUND)
    resp = HttpResponse(render_pdf(inv), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="invoice-{inv.number.replace("/", "-")}.pdf"'
    resp["Cache-Control"] = "no-store"
    return resp


# ── Org seats ────────────────────────────────────────────────────────


def _truthy(v) -> bool:
    """JSON true, or a form/query string like "true"/"1" ("false" and "0" are False, unlike bool())."""
    return (
        v is True
        or (isinstance(v, int | float) and not isinstance(v, bool) and v != 0)
        or str(v).strip().lower() in ("true", "1", "yes", "on")
    )


@api_view(["GET", "POST"])
def org_billing(request, slug):
    """GET: seats, subscription, codes, invoices. POST {membership_id, seat}: give / take a seat."""
    from apps.orgs.models import Membership
    from apps.orgs.perms import require

    me = require(request.user, slug, "admin")
    org = me.org
    if request.method == "POST":
        from apps.orgs.models import Organization

        try:
            mid = int(request.data.get("membership_id"))
        except (TypeError, ValueError):
            return Response({"code": "bad_membership"}, status=status.HTTP_400_BAD_REQUEST)
        want = _truthy(request.data.get("seat"))
        with transaction.atomic():
            Organization.objects.select_for_update().filter(
                pk=org.pk
            ).first()  # two admins can't both give the last seat
            m = get_object_or_404(Membership, pk=mid, org=org)
            if (
                want
                and not m.seat
                and Membership.objects.filter(org=org, seat=True).count() >= seats_total(org)
            ):
                return Response({"code": "no_free_seats"}, status=status.HTTP_409_CONFLICT)
            m.seat = want
            m.save(update_fields=["seat"])
    now = timezone.now()
    sub = (
        OrgSubscription.objects.filter(org=org, ends_at__gt=now)
        .select_related("plan")
        .order_by("-ends_at")
        .first()
    )
    orders = (
        Order.objects.filter(org=org, status="paid")
        .select_related("plan", "invoice")
        .order_by("-paid_at")[:30]
    )
    return Response(
        {
            "subscription": {
                "plan": sub.plan.name,
                "plan_code": sub.plan.code,
                "seats": sub.seats,
                "starts_at": sub.starts_at,
                "ends_at": sub.ends_at,
            }
            if sub
            else None,
            "seats_total": seats_total(org),
            "seats_used": Membership.objects.filter(org=org, seat=True).count(),
            "learners": Membership.objects.filter(org=org, role="learner").count(),
            "orders": [
                {
                    "id": o.id,
                    "plan": o.plan.name,
                    "seats": o.seats,
                    "amount_paise": o.amount_paise,
                    "paid_at": o.paid_at,
                    "invoice": o.invoice.number if hasattr(o, "invoice") else None,
                }
                for o in orders
            ],
            "redeem_codes": {
                "total": org.redeem_codes.count(),
                "used": org.redeem_codes.filter(redeemed_at__isnull=False).count(),
            },
        }
    )


@api_view(["POST"])
def org_assign_seats(request, slug):
    from apps.orgs.perms import require

    me = require(request.user, slug, "admin")
    return Response({"assigned": assign_seats(me.org)})


@api_view(["GET"])
def org_redeem_codes(request, slug):
    """A school's prepaid codes (to print / hand out). ?export=csv downloads them (?format= is DRF's renderer switch)."""
    from apps.orgs.perms import require

    me = require(request.user, slug, "admin")
    rows = me.org.redeem_codes.select_related("plan", "redeemed_by").order_by("batch", "code")
    return _codes_response(request, rows, f"{me.org.slug}-codes.csv")


def _codes_response(request, rows, filename):
    data = [
        {
            "code": r.code,
            "plan": r.plan.name,
            "days": r.days,
            "batch": r.batch,
            "expires_at": r.expires_at,
            "redeemed": bool(r.redeemed_at),
            "redeemed_by": r.redeemed_by.email if r.redeemed_by_id and request.user.is_staff else None,
        }
        for r in rows
    ]
    if request.query_params.get("export") == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["code", "plan", "days", "batch", "expires", "redeemed"])
        for d in data:
            w.writerow(
                [
                    csv_safe(d["code"]),
                    csv_safe(d["plan"]),
                    d["days"],
                    csv_safe(d["batch"]),
                    d["expires_at"] or "",
                    "yes" if d["redeemed"] else "",
                ]
            )
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp
    return Response(data)


# ── Super admin: promo + redeem codes ────────────────────────────────


class PromoSer(serializers.ModelSerializer):
    class Meta:
        model = PromoCode
        fields = [
            "id",
            "code",
            "kind",
            "value",
            "plans",
            "expires_at",
            "max_uses",
            "uses",
            "per_user",
            "max_seats",
            "active",
            "note",
            "purpose",
            "created_at",
        ]
        read_only_fields = ["uses", "created_at"]

    def validate_code(self, v):
        v = v.strip().upper()
        if not v.replace("-", "").replace("_", "").isalnum() or not 3 <= len(v) <= 32:
            raise serializers.ValidationError("letters_digits_only")
        return v

    def validate(self, d):
        kind = d.get("kind", getattr(self.instance, "kind", "percent"))
        value = d.get("value", getattr(self.instance, "value", 0))
        if kind not in ("percent", "fixed") or value < 1 or (kind == "percent" and value > 100):
            raise serializers.ValidationError({"value": "bad_value"})
        plans = d.get("plans")
        if plans and not set(plans) <= set(Plan.objects.values_list("code", flat=True)):
            raise serializers.ValidationError({"plans": "unknown_plan"})
        return d


@api_view(["GET", "POST"])
@permission_classes([AdminSection])
def admin_promos(request):
    if request.method == "POST":
        ser = PromoSer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)
    return Response(PromoSer(PromoCode.objects.order_by("-created_at")[:200], many=True).data)


@api_view(["PATCH", "DELETE"])
@permission_classes([AdminSection])
def admin_promo(request, pk):
    p = get_object_or_404(PromoCode, pk=pk)
    if request.method == "DELETE":
        if p.orders.exists():  # keep for the tax trail; just switch it off
            p.active = False
            p.save(update_fields=["active"])
            return Response(PromoSer(p).data)
        p.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = PromoSer(p, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)


class RedeemBatch(serializers.Serializer):
    plan = serializers.SlugField()
    days = serializers.IntegerField(min_value=1, max_value=730)
    count = serializers.IntegerField(min_value=1, max_value=1000)
    batch = serializers.CharField(max_length=80)
    org = serializers.SlugField(required=False, allow_blank=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


@api_view(["GET", "POST"])
@permission_classes([AdminSection])
def admin_redeem_codes(request):
    if request.method == "POST":
        ser = RedeemBatch(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        plan = get_object_or_404(Plan, code=d["plan"])
        org = None
        if d.get("org"):
            from apps.orgs.models import Organization

            org = get_object_or_404(Organization, slug=d["org"])
        codes = set()
        while len(codes) < d["count"]:
            c = _new_code()
            if not RedeemCode.objects.filter(code=c).exists():
                codes.add(c)
        RedeemCode.objects.bulk_create(
            [
                RedeemCode(
                    code=c,
                    plan=plan,
                    days=d["days"],
                    batch=d["batch"],
                    org=org,
                    expires_at=d.get("expires_at"),
                    created_by=request.user,
                )
                for c in sorted(codes)
            ]
        )
        return Response({"created": len(codes), "batch": d["batch"]}, status=status.HTTP_201_CREATED)
    rows = RedeemCode.objects.select_related("plan", "redeemed_by").order_by("-created_at")
    if b := request.query_params.get("batch"):
        rows = rows.filter(batch=b)
    return _codes_response(request, rows[:2000], "redeem-codes.csv")


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_invoices(request):
    rows = Invoice.objects.select_related("order").order_by("-issued_at")[:300]
    return Response(
        [
            {
                "number": i.number,
                "issued_at": i.issued_at,
                "buyer": i.buyer.get("name"),
                "total_paise": i.total_paise,
                "taxable_paise": i.taxable_paise,
                "gst_paise": i.cgst_paise + i.sgst_paise + i.igst_paise,
                "mode": i.order.mode,
            }
            for i in rows
        ]
    )
