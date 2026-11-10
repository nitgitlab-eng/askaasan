"""Plans, entitlements, free-plan limits and the payment → access grant."""

import logging
import os
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Entitlement, Order, PaymentConfig, Plan, UsageEvent
from .razorpay import Keys

log = logging.getLogger(__name__)


# ── Razorpay config: admin console first, then .env ──────────────────


@dataclass
class PayConfig:
    key_id: str
    secret: str
    webhook_secret: str
    enabled: bool
    allow_live: bool
    business_name: str
    source: dict  # which of key_id / secret / webhook_secret came from "admin" or "env"

    @property
    def keys(self) -> Keys:
        return Keys(self.key_id, self.secret)

    @property
    def mode(self) -> str | None:
        return self.keys.mode if self.key_id else None

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.key_id and self.secret) and (self.mode == "test" or self.allow_live)


def pay_config() -> PayConfig:
    row = PaymentConfig.objects.filter(pk=1).first()
    vals, src = {}, {}
    for field, env, getter in (
        ("key_id", "RAZORPAY_KEY_ID", lambda r: r.key_id),
        ("secret", "RAZORPAY_KEY_SECRET", lambda r: r.secret()),
        ("webhook_secret", "RAZORPAY_WEBHOOK_SECRET", lambda r: r.webhook_secret()),
    ):
        db = getter(row) if row else ""
        vals[field] = db or os.environ.get(env, "")
        src[field] = "admin" if db else ("env" if vals[field] else None)
    return PayConfig(
        **vals,
        enabled=row.enabled if row else True,
        allow_live=row.allow_live if row else False,
        business_name=row.business_name if row else "Aasan",
        source=src,
    )


# ── Plans & entitlements ─────────────────────────────────────────────


class _Unlimited:
    code, name, limits, price_paise, period_days = "staff", "Staff", {}, 0, 0


# Used only if the "free" plan row is missing: a missing row must not mean unlimited (limits={} would).
FREE_FALLBACK_LIMITS = {
    "ai_courses_per_month": 2,
    "mentor_messages_per_day": 30,
    "documents": 3,
    "voice_minutes_per_day": 10,
    "tts_chars_per_day": 5000,
    "live_minutes_per_day": 10,
    "lab_ai_per_day": 20,
}


def free_plan() -> Plan:
    return Plan.objects.filter(code="free").first() or Plan(
        code="free", name="Free", limits=dict(FREE_FALLBACK_LIMITS)
    )


def active_entitlement(user) -> Entitlement | None:
    """The window giving access right now. Overlapping windows (own plan + a family share): the highest-priced plan
    wins, the same rule as plan versus org seat."""
    return (
        Entitlement.objects.filter(user=user, starts_at__lte=timezone.now(), ends_at__gt=timezone.now())
        .select_related("plan")
        .order_by("-plan__price_paise", "-ends_at")
        .first()
    )


def seat_plan(user):
    """The plan from an org seat the user holds (school/company paid), if any. A seat only counts while it is within the
    org's paid seat count (seat holders ranked oldest first), and gives the plan of the subscription that pays for it."""
    from apps.orgs.models import Membership

    best = None
    for m in Membership.objects.filter(user=user, seat=True).only("id", "org_id"):
        sub = active_seat_sub(m.org_id)
        if not sub or Membership.objects.filter(org_id=m.org_id, seat=True, id__lt=m.id).count() >= sub.seats:
            continue
        if best is None or sub.plan.price_paise > best.price_paise:
            best = sub.plan
    return best


def current_plan(user):
    if user.is_staff:
        return _Unlimited()
    ent = active_entitlement(user)
    seat = seat_plan(user)
    if ent and seat:
        return ent.plan if ent.plan.price_paise >= seat.price_paise else seat
    return ent.plan if ent else seat or free_plan()


def paid_until(user, *, own=False):
    """When the user's access runs out. own=True leaves out a family share (which the owner controls)."""
    qs = Entitlement.objects.filter(user=user, ends_at__gt=timezone.now())
    if own:
        qs = qs.exclude(source="family")
    return qs.aggregate(m=Max("ends_at"))["m"]


def _extend(user, plan, days, *, order=None, source="payment", granted_by=None, note="") -> Entitlement:
    """Stack new access after any time already paid for, so renewing early never loses days. A family share doesn't
    count: it can end whenever the owner removes someone, so the person's own time runs alongside it."""
    start = max(timezone.now(), paid_until(user, own=True) or timezone.now())
    ent = Entitlement.objects.create(
        user=user,
        plan=plan,
        starts_at=start,
        ends_at=start + timedelta(days=days),
        order=order,
        source=source,
        granted_by=granted_by,
        note=note,
    )
    from . import family

    family.on_owner_grant(
        ent
    )  # a family owner's new window reaches every member (checkout, renewal, grace, codes)
    return ent


def grant_for_order(order_id: int, payment_id: str):
    """Idempotent: the browser callback and the webhook can both land; only the first grants access.
    Personal orders → an Entitlement; org orders → an OrgSubscription (seats). Issues the GST invoice.
    Returns None (nothing granted, staff alerted) if the order's promo was used up while the order sat unpaid."""
    from django.db.models import F

    from .invoices import issue_invoice
    from .models import OrgSubscription, PromoCode

    with transaction.atomic():
        order = (
            Order.objects.select_for_update(of=("self",))
            .select_related("plan", "user", "org")
            .get(pk=order_id)
        )
        if order.status == Order.Status.PAID:
            if order.is_gift:  # a duplicate callback/webhook for a gift: the code already exists
                return order.gift
            if order.workshop_run_id:  # None when the seat was refused at capture (order.error says why)
                from apps.workshops.models import WorkshopEnrollment

                return WorkshopEnrollment.objects.filter(order=order).first()
            return (
                OrgSubscription.objects.filter(order=order).first()
                if order.org_id
                else Entitlement.objects.get(order=order)
            )
        if order.promo_id and _promo_used_up(order):
            first = order.error != PROMO_USED_UP  # the callback and the webhook both land; alert once
            order.rp_payment_id, order.error = payment_id, PROMO_USED_UP
            order.save(update_fields=["rp_payment_id", "error"])
            if first:
                transaction.on_commit(lambda: _alert_promo_used_up(order, payment_id))
            return None
        order.status, order.rp_payment_id, order.paid_at, order.error = (
            Order.Status.PAID,
            payment_id,
            timezone.now(),
            "",
        )
        order.save()
        if order.promo_id:
            PromoCode.objects.filter(pk=order.promo_id).update(uses=F("uses") + 1)
        if order.workshop_run_id:
            from apps.workshops.public import grant_seat

            grant = grant_seat(order)  # a seat on a public workshop run, re-checked under the run's row lock
            if grant is None:  # paid, no seat (full/closed/cancelled): staff refund it, no invoice
                return None
        elif order.org_id:
            grant = extend_org(order.org, order.plan, order.seats, order=order)
        elif order.is_gift:
            from .gifts import fulfil

            grant = fulfil(order)  # a redeem code for the recipient, emailed after commit
        else:
            grant = _extend(order.user, order.plan, order.plan.period_days, order=order)
        if order.amount_paise > 0:
            issue_invoice(order)
    _send_receipt(order, grant)
    return grant


def _sub_value(sub) -> int:
    """Paise-seconds a subscription still has paid for: seats × plan price over its remaining time, scaled by what its
    order actually paid (a 60% promo keeps 40% of the value, a free/100% promo or an order-less grant keeps none)."""
    now = timezone.now()
    left = (sub.ends_at - max(sub.starts_at, now)).total_seconds()
    period = sub.plan.period_days * 86400
    order = sub.order
    full = (order.list_paise or sub.seats * sub.plan.price_paise) if order else 0
    if left <= 0 or not period or not full:
        return 0
    paid_share = min(1.0, order.amount_paise / full)
    return int(sub.seats * sub.plan.price_paise * left / period * paid_share)


PROMO_USED_UP = "promo_used_up"


def _promo_used_up(order) -> bool:
    """Re-check the promo's limits at capture (row locked). Checkout reserves a use only while the order is fresh and
    unfailed, but the gateway order stays payable after that, so a lapsed checkout must not take a use someone else has."""
    from .models import PromoCode

    p = PromoCode.objects.select_for_update().filter(pk=order.promo_id).first()
    if not p:
        return False
    if p.max_uses and p.uses >= p.max_uses:
        return True
    others = (
        Order.objects.filter(promo=p, user=order.user, status=Order.Status.PAID).exclude(pk=order.pk).count()
        if order.user_id
        else 0
    )
    return bool(p.per_user and others >= p.per_user)


def _alert_promo_used_up(order, payment_id):
    log.warning(
        "order %s paid (%s) after its promo was used up; not granted, refund by hand",
        order.rp_order_id,
        payment_id,
    )
    from django.core.mail import mail_admins

    try:
        mail_admins(
            "Payment for a used-up promo",
            f"Order {order.rp_order_id} was paid ({payment_id}) after promo #{order.promo_id} "
            "reached its limit. Access was not granted: refund it from the Razorpay dashboard, or grant it by hand.",
            fail_silently=True,
        )
    except Exception:
        log.exception("promo alert failed")


def extend_org(org, plan, seats, *, order=None):
    """Org seat purchase: the same plan and size stacks after the current subscription. A different plan or size starts
    now and replaces what's running: the unused paid time of the old subscriptions becomes extra days on the new one
    (pro rata by seats × price), so nothing paid is wasted and only one seat count is ever live."""
    from apps.orgs.models import Organization

    from .models import OrgSubscription

    with transaction.atomic():
        Organization.objects.select_for_update().filter(pk=org.pk).first()
        now = timezone.now()
        running = list(
            OrgSubscription.objects.filter(org=org, ends_at__gt=now)
            .select_related("plan", "order")
            .order_by("-ends_at")
        )
        current = running[0] if running else None
        if current and current.plan_id == plan.id and current.seats == seats:
            start, end = current.ends_at, current.ends_at + timedelta(days=plan.period_days)
        else:
            start, end = now, now + timedelta(days=plan.period_days)
            credit = sum(_sub_value(s) for s in running)
            rate = seats * plan.price_paise / (plan.period_days * 86400) if plan.period_days else 0
            if credit and rate:
                end += timedelta(seconds=credit / rate)
            for s in running:  # replaced: end now (or never start, for renewals stacked in the future)
                s.ends_at = max(s.starts_at, now)
                s.save(update_fields=["ends_at"])
        sub = OrgSubscription.objects.create(
            org=org, plan=plan, seats=seats, starts_at=start, ends_at=end, order=order
        )
        assign_seats(org)
    return sub


def active_seat_sub(org_id):
    """The subscription paying for an org's seats right now (the largest, if old ones overlap)."""
    from .models import OrgSubscription

    now = timezone.now()
    return (
        OrgSubscription.objects.filter(org_id=org_id, starts_at__lte=now, ends_at__gt=now)
        .select_related("plan")
        .order_by("-seats", "-plan__price_paise")
        .first()
    )


def seats_total(org) -> int:
    sub = active_seat_sub(org.pk)
    return sub.seats if sub else 0


def assign_seats(org) -> int:
    """Fill free seats with learners (oldest members first). Returns how many were assigned.
    Holds the org row, so two joiners (or a joiner and an admin) can't both take the last seat."""
    from apps.orgs.models import Membership, Organization

    with transaction.atomic():
        Organization.objects.select_for_update().filter(pk=org.pk).first()
        free = seats_total(org) - Membership.objects.filter(org=org, seat=True).count()
        if free <= 0:
            return 0
        ids = list(
            Membership.objects.filter(org=org, role="learner", seat=False)
            .order_by("joined_at")
            .values_list("id", flat=True)[:free]
        )
        Membership.objects.filter(id__in=ids).update(seat=True)
    return len(ids)


def manual_grant(user, plan, days, admin, note="") -> Entitlement:
    with transaction.atomic():
        return _extend(user, plan, days, source="grant", granted_by=admin, note=note)


def _send_receipt(order, ent):
    if not order.user_id:
        return
    if order.workshop_run_id:
        from apps.workshops.public import send_receipt

        return send_receipt(order, ent)
    from django.core.mail import send_mail

    if order.is_gift:
        try:
            send_mail(
                f"Aasan payment received — {order.label}",
                f"Thank you! We received ₹{order.amount_paise / 100:,.2f} for a gift of {order.plan.name}.\n"
                f"We've emailed the gift code to {order.gift.recipient_email}. "
                "You'll get a note when they start using it.\n"
                f"Payment ID: {order.rp_payment_id}\nOrder ID: {order.rp_order_id}"
                + (
                    "\n\n(This was a TEST MODE payment — no real money moved.)"
                    if order.mode == "test"
                    else ""
                ),
                None,
                [order.user.email],
                fail_silently=True,
            )
        except Exception:  # never let email break a payment
            log.exception("receipt email failed")
        return
    try:
        send_mail(
            f"Aasan payment received — {order.plan.name}",
            f"Thank you! We received ₹{order.amount_paise / 100:,.2f} for {order.plan.name}.\n"
            f"{'Seats for ' + order.org.name + ' run' if order.org_id else 'Your access runs'} until {timezone.localtime(ent.ends_at):%d %b %Y}.\n"
            f"Payment ID: {order.rp_payment_id}\nOrder ID: {order.rp_order_id}"
            + ("\n\n(This was a TEST MODE payment — no real money moved.)" if order.mode == "test" else ""),
            None,
            [order.user.email],
            fail_silently=True,
        )
    except Exception:  # never let email break a payment
        log.exception("receipt email failed")


# ── Limits ───────────────────────────────────────────────────────────


class PlanLimit(Exception):
    def __init__(self, key, used, maximum, plan):
        super().__init__(key)
        self.key, self.used, self.max, self.plan = key, used, maximum, plan

    def payload(self) -> dict:
        return {
            "code": "plan_limit",
            "limit": self.key,
            "used": self.used,
            "max": self.max,
            "plan": self.plan,
        }


def _day_start():
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def usage(user, key: str) -> float:
    if key == "ai_courses_per_month":
        return UsageEvent.objects.filter(
            user=user, metric="ai_course", created_at__gte=timezone.now() - timedelta(days=30)
        ).count()
    if key == "mentor_messages_per_day":
        # Counted when sent (not from live chat rows), so deleting chats can't reset the limit.
        return UsageEvent.objects.filter(
            user=user, metric="mentor_message", created_at__gte=_day_start()
        ).count()
    if key == "lab_ai_per_day":
        return UsageEvent.objects.filter(user=user, metric="lab_ai", created_at__gte=_day_start()).count()
    if key == "documents":
        from apps.docs.models import Document

        return Document.objects.filter(owner=user).count()
    if key == "voice_minutes_per_day":
        from apps.providers.models import UsageCounter

        row = UsageCounter.objects.filter(user=user, day=timezone.localdate(), metric="stt_seconds").first()
        return round((row.amount if row else 0) / 60, 1)
    if key == "tts_chars_per_day":
        from apps.providers.models import UsageCounter

        row = UsageCounter.objects.filter(user=user, day=timezone.localdate(), metric="tts_chars").first()
        return int(row.amount if row else 0)
    if key == "live_minutes_per_day":
        from apps.providers.models import UsageCounter

        row = UsageCounter.objects.filter(user=user, day=timezone.localdate(), metric="live_seconds").first()
        return round((row.amount if row else 0) / 60, 1)
    raise KeyError(key)


def limit_of(user, key: str):
    plan = current_plan(user)
    v = plan.limits.get(key)
    if v is None and key not in plan.limits and getattr(plan, "code", "") == "free":
        # A key dropped from the free plan must not mean unlimited; an explicit null still does.
        v = FREE_FALLBACK_LIMITS.get(key)
    return v


def check(user, key: str, adding: float = 1) -> None:
    """Raise PlanLimit if one more unit would pass the user's plan limit.
    On its own this is advisory: parallel requests can all pass before any records. Use consume() (or call check()
    and record inside `with transaction.atomic(): lock_user(user)`) where the limit must hold."""
    maximum = limit_of(user, key)
    if maximum is None:
        return
    used = usage(user, key)
    if used + adding > maximum:
        raise PlanLimit(key, used, maximum, current_plan(user).code)


def record(user, metric: str) -> None:
    UsageEvent.objects.create(user=user, metric=metric)


def lock_user(user) -> None:
    """Serialise one user's limit checks: hold their row until the surrounding transaction ends."""
    from django.contrib.auth import get_user_model

    get_user_model().objects.select_for_update().filter(pk=user.pk).first()


def consume(user, key: str, metric: str, n: int = 1) -> None:
    """Atomic check-and-record: raise PlanLimit, or record `n` uses of `metric`, with the user's row locked so parallel
    requests can't all pass the check before any of them records."""
    with transaction.atomic():
        lock_user(user)
        check(user, key, adding=n)
        UsageEvent.objects.bulk_create([UsageEvent(user=user, metric=metric) for _ in range(n)])


def plan_out(p, *, with_limits=True) -> dict:
    out = {"code": p.code, "name": p.name, "price_paise": p.price_paise, "period_days": p.period_days}
    if isinstance(p, Plan):
        from .subscriptions import offers_auto_renew

        out.update(
            description=p.description,
            badge=p.badge,
            auto_renew=offers_auto_renew(p),
            family=p.family,
            max_members=p.max_members if p.family else 0,
        )
    if with_limits:
        out["limits"] = p.limits
    return out
