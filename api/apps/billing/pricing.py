"""Quotes: list price × seats, promo discount, the final GST-inclusive amount. One place, used by quote and checkout."""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from .models import Order, Plan, PromoCode

MIN_GATEWAY_PAISE = 100  # Razorpay minimum (₹1)


class PromoError(ValueError):
    pass


@dataclass
class Quote:
    plan: Plan
    seats: int
    list_paise: int
    discount_paise: int
    promo: PromoCode | None

    @property
    def total_paise(self) -> int:
        total = max(0, self.list_paise - self.discount_paise)
        return MIN_GATEWAY_PAISE if 0 < total < MIN_GATEWAY_PAISE else total

    def out(self) -> dict:
        return {
            "plan": self.plan.code,
            "seats": self.seats,
            "list_paise": self.list_paise,
            "discount_paise": self.discount_paise,
            "total_paise": self.total_paise,
            "promo": self.promo.code if self.promo else None,
            "promo_note": self.promo.note if self.promo else "",
        }


HOLD = timedelta(minutes=30)  # an unpaid checkout keeps its promo use reserved this long


def _holding(qs):
    """Orders that count against a promo: paid, or started recently and not yet paid/failed."""
    return qs.filter(Q(status="paid") | Q(status="created", created_at__gte=timezone.now() - HOLD))


def find_promo(code: str, plan: Plan, user, seats: int = 1, lock=False, for_org=False) -> PromoCode:
    """Every failure is the same "promo_invalid", so codes can't be probed for which ones exist.
    lock=True (checkout, inside a transaction) holds the promo row so parallel checkouts can't all pass the use limits."""
    qs = PromoCode.objects.select_for_update() if lock else PromoCode.objects
    p = qs.filter(code=(code or "").strip().upper(), active=True).first()
    if (
        not p
        or p.expires_at
        and p.expires_at < timezone.now()
        or p.plans
        and plan.code not in p.plans
        or for_org
        and not (p.max_seats and seats <= p.max_seats)
    ):  # school seats only when the promo allows them
        raise PromoError("promo_invalid")
    if p.max_uses and p.uses + _holding(p.orders.filter(status="created")).count() >= p.max_uses:
        raise PromoError("promo_invalid")
    if p.per_user and _holding(Order.objects.filter(user=user, promo=p)).count() >= p.per_user:
        raise PromoError("promo_invalid")
    return p


def quote(user, plan: Plan, seats: int = 1, promo_code: str = "", lock=False, for_org=False) -> Quote:
    list_paise = plan.price_paise * seats
    promo, discount = None, 0
    if promo_code:
        promo = find_promo(promo_code, plan, user, seats, lock, for_org)
        discount = (
            list_paise * min(promo.value, 100) // 100
            if promo.kind == "percent"
            else min(promo.value, list_paise)
        )
    return Quote(plan, seats, list_paise, discount, promo)
