"""Super-admin console: Razorpay keys, plans, payments, manual grants."""

from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.db.models import Count, Q, Sum
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.staff import AdminSection
from apps.providers import crypto

from . import razorpay as rp
from .models import LIMIT_KEYS, Order, PaymentConfig, Plan
from .services import manual_grant, pay_config
from .subscriptions import PAYMENT_EVENTS, SUBSCRIPTION_EVENTS

admin_only = permission_classes([AdminSection])


def _masked(v):
    return crypto.mask(v) if v else None


def _config_out():
    c = pay_config()
    return {
        "key_id": c.key_id,
        "mode": c.mode,
        "enabled": c.enabled,
        "allow_live": c.allow_live,
        "ready": c.ready,
        "business_name": c.business_name,
        "secret": _masked(c.secret),
        "webhook_secret": _masked(c.webhook_secret),
        "source": c.source,
        "webhook_path": "/api/billing/webhook/",
        "webhook_events": SUBSCRIPTION_EVENTS + PAYMENT_EVENTS,
    }


class ConfigPatch(serializers.Serializer):
    key_id = serializers.RegexField(r"^(rzp_test_|rzp_live_)[A-Za-z0-9]+$|^$", required=False, max_length=64)
    key_secret = serializers.CharField(required=False, allow_blank=True, max_length=128, trim_whitespace=True)
    webhook_secret = serializers.CharField(
        required=False, allow_blank=True, max_length=128, trim_whitespace=True
    )
    enabled = serializers.BooleanField(required=False)
    allow_live = serializers.BooleanField(required=False)
    business_name = serializers.CharField(required=False, max_length=80)


@api_view(["GET", "PATCH"])
@admin_only
def config(request):
    if request.method == "PATCH":
        ser = ConfigPatch(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        row, _ = PaymentConfig.objects.get_or_create(pk=1)
        allow_live = d.get("allow_live", row.allow_live)
        if d.get("key_id", "").startswith("rzp_live_") and not allow_live:
            return Response(
                {"code": "live_not_allowed", "detail": "Turn on 'Allow live payments' to save a live key."},
                status=400,
            )
        if "key_id" in d and d["key_id"] != row.key_id:
            row.key_id = d["key_id"]
            if "key_secret" not in d:
                row.encrypted_secret = ""  # a secret belongs to exactly one key id
        if "key_secret" in d:
            row.encrypted_secret = crypto.encrypt(d["key_secret"]) if d["key_secret"] else ""
        if "webhook_secret" in d:
            row.encrypted_webhook_secret = crypto.encrypt(d["webhook_secret"]) if d["webhook_secret"] else ""
        for f in ("enabled", "allow_live", "business_name"):
            if f in d:
                setattr(row, f, d[f])
        row.updated_by = request.user
        row.save()
    return Response(_config_out())


@api_view(["POST"])
@admin_only
def test_keys(request):
    c = pay_config()
    if not (c.key_id and c.secret):
        return Response(
            {"ok": False, "code": "missing_key", "detail": "Save the Key ID and Key Secret first."},
            status=400,
        )
    try:
        rp.ping(c.keys)
    except rp.RazorpayError as e:
        return Response({"ok": False, "code": e.code, "detail": str(e)}, status=400)
    return Response({"ok": True, "detail": f"Connected to Razorpay ({c.mode} mode)."})


class PlanSer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id",
            "code",
            "name",
            "description",
            "price_paise",
            "period_days",
            "limits",
            "badge",
            "active",
            "sort",
            "rp_plan_id",
            "auto_renew",
            "family",
            "max_members",
        ]
        extra_kwargs = {
            "rp_plan_id": {
                "validators": [
                    RegexValidator(
                        r"^(plan_[A-Za-z0-9]{6,32})?$", "Razorpay plan ids look like plan_XXXXXXXX"
                    )
                ]
            }
        }

    def validate_limits(self, v):
        if not isinstance(v, dict) or set(v) - set(LIMIT_KEYS):
            raise serializers.ValidationError(f"allowed limits: {list(LIMIT_KEYS)}")
        for k, x in v.items():
            if x is not None and (not isinstance(x, (int, float)) or x < 0):
                raise serializers.ValidationError(f"{k} must be a number ≥ 0, or null for unlimited")
        return v

    def validate(self, d):
        price = d.get("price_paise", getattr(self.instance, "price_paise", 0))
        if price and price < 100:
            raise serializers.ValidationError({"price_paise": "Razorpay needs at least ₹1 (100 paise)."})
        if price and not d.get("period_days", getattr(self.instance, "period_days", 0)):
            raise serializers.ValidationError({"period_days": "Paid plans need a period."})
        code = d.get("code", getattr(self.instance, "code", ""))
        if code == "free" and price:
            raise serializers.ValidationError({"price_paise": "The free plan must stay ₹0."})
        max_members = d.get("max_members", getattr(self.instance, "max_members", 5))
        if not 2 <= max_members <= 20:
            raise serializers.ValidationError({"max_members": "A family has 2 to 20 people."})
        if d.get("family", getattr(self.instance, "family", False)) and (not price or code == "free"):
            raise serializers.ValidationError({"family": "Only paid plans can be family plans."})
        if d.get("auto_renew", getattr(self.instance, "auto_renew", False)):
            if not price or code == "free":
                raise serializers.ValidationError({"auto_renew": "Only paid plans can auto-renew."})
            if not d.get("rp_plan_id", getattr(self.instance, "rp_plan_id", "")):
                raise serializers.ValidationError(
                    {"rp_plan_id": "Add the Razorpay plan id before offering auto-renew."}
                )
        return d


@api_view(["GET", "POST"])
@admin_only
def plans(request):
    if request.method == "POST":
        ser = PlanSer(data=request.data)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data, status=status.HTTP_201_CREATED)
    return Response(PlanSer(Plan.objects.all(), many=True).data)


@api_view(["PATCH"])
@admin_only
def plan_detail(request, pk):
    p = Plan.objects.filter(pk=pk).first()
    if not p:
        return Response(status=status.HTTP_404_NOT_FOUND)
    data = dict(request.data)
    if p.code == "free":
        data.pop("code", None)
        data.pop("active", None)  # the free plan is the fallback; it can't be switched off
    ser = PlanSer(p, data=data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(ser.data)


@api_view(["GET"])
@admin_only
def orders(request):
    """?mode=test|live &status= &q= (email / Razorpay id) &page= (50 a page) &export=csv"""
    from apps.accounts.admin_paging import PAGE_SIZE, paged

    from .refunds import refunded

    mode = request.query_params.get("mode")
    qs = Order.objects.select_related("user", "plan", "workshop_run__workshop", "gift")
    if mode in ("test", "live"):
        qs = qs.filter(mode=mode)
    paid = qs.filter(status=Order.Status.PAID)
    by_plan = (
        paid.values("plan__name").annotate(n=Count("id"), revenue=Sum("amount_paise")).order_by("-revenue")
    )
    listed = qs
    if (st := request.query_params.get("status")) in Order.Status.values:
        listed = listed.filter(status=st)
    if q := str(request.query_params.get("q") or "").strip()[:80]:
        listed = listed.filter(
            Q(user__email__icontains=q) | Q(rp_payment_id__icontains=q) | Q(rp_order_id__icontains=q)
        )
    listed = listed.order_by("-created_at")

    def row(o):
        return {
            "id": o.id,
            "email": o.user.email if o.user else "(deleted account)",
            "plan": o.label,
            "amount_paise": o.amount_paise,
            "refunded_paise": refunded(o),
            "status": o.status,
            "mode": o.mode,
            "created_at": o.created_at,
            "paid_at": o.paid_at,
            "payment_id": o.rp_payment_id,
            "order_id": o.rp_order_id,
            "error": o.error,
        }

    if request.query_params.get("export") == "csv":
        return paged(request, listed, row, name="orders")
    try:
        page = max(1, int(request.query_params.get("page") or 1))
    except ValueError:
        page = 1
    count = listed.count()
    return Response(
        {
            "summary": {
                "paid": paid.count(),
                "revenue_paise": paid.aggregate(s=Sum("amount_paise"))["s"] or 0,
                "failed": qs.filter(status=Order.Status.FAILED).count(),
                "by_plan": list(by_plan),
            },
            "orders": [row(o) for o in listed[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]],
            "count": count,
            "page": page,
            "pages": max(1, -(-count // PAGE_SIZE)),
        }
    )


@api_view(["POST"])
@admin_only
def grant(request):
    user = get_user_model().objects.filter(email__iexact=(request.data.get("email") or "").strip()).first()
    plan = Plan.objects.filter(code=request.data.get("plan"), price_paise__gt=0).first()
    try:
        days = int(request.data.get("days") or (plan.period_days if plan else 0))
    except (TypeError, ValueError):
        days = 0
    if not user:
        return Response({"code": "user_not_found"}, status=404)
    if not plan or not 1 <= days <= 3660:
        return Response({"code": "bad_request"}, status=400)
    ent = manual_grant(user, plan, days, request.user, (request.data.get("note") or "")[:200])
    return Response({"ok": True, "email": user.email, "plan": plan.name, "ends_at": ent.ends_at})
