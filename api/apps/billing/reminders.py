"""Plan-expiry reminders: 3 days before the paid time runs out, and once it has ended. Safe to run repeatedly."""

from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from .models import Entitlement

SOON = timedelta(days=3)


def _notify(user, title, body):
    from apps.accounts.notify import send_optional
    from apps.game.models import Notification

    Notification.objects.create(user=user, kind="plan", title=title, body=body, link="/plans")
    send_optional(user, "email_plan", title, f"{body}\n\nRenew any time from the Plans page in Aasan.")
    from apps.accounts.push import send as push

    push(user, "plan", title, body, "/plans")


def _renews(user) -> bool:
    """Auto-renew is on: the next charge extends access, so there's nothing to remind about."""
    from .models import Subscription

    return Subscription.objects.filter(
        user=user, status__in=("authenticated", "active", "pending"), cancel_at_period_end=False
    ).exists()


def send_due(now=None) -> dict:
    from .services import seat_plan

    now = now or timezone.now()
    sent = {"soon": 0, "ended": 0}
    # Remind on the *last* window per user only — someone who renewed early has a later one.
    latest = {r["user"]: r["m"] for r in Entitlement.objects.values("user").annotate(m=Max("ends_at"))}
    # A family member's copy is the owner's to renew: only the owner is reminded.
    for ent in (
        Entitlement.objects.filter(ends_at__gt=now, ends_at__lte=now + SOON, reminded_soon_at__isnull=True)
        .exclude(source="family")
        .select_related("user", "plan")
    ):
        # Claim first, atomically: an overlapping beat run or a redelivered task can't remind twice.
        if not Entitlement.objects.filter(pk=ent.pk, reminded_soon_at__isnull=True).update(
            reminded_soon_at=now
        ):
            continue
        seat = ent.user and seat_plan(ent.user)
        # A school/company seat on the same or a better plan carries on, so the paid time ending changes nothing.
        if (
            ent.user
            and ent.ends_at == latest.get(ent.user_id)
            and not _renews(ent.user)
            and not (seat and seat.price_paise >= ent.plan.price_paise)
        ):
            _notify(
                ent.user,
                f"Your {ent.plan.name} ends on {timezone.localtime(ent.ends_at):%d %b}",
                "Renew before then to keep your extra courses, chats and voice time.",
            )
            sent["soon"] += 1
    for ent in (
        Entitlement.objects.filter(
            ends_at__lte=now, ends_at__gt=now - timedelta(days=7), reminded_end_at__isnull=True
        )
        .exclude(source="family")
        .select_related("user", "plan")
    ):
        if not Entitlement.objects.filter(pk=ent.pk, reminded_end_at__isnull=True).update(
            reminded_end_at=now
        ):
            continue
        seat = ent.user and seat_plan(ent.user)
        if (
            ent.user
            and ent.ends_at == latest.get(ent.user_id)
            and not _renews(ent.user)
            and not (seat and seat.price_paise >= ent.plan.price_paise)
        ):
            _notify(
                ent.user,
                f"Your {ent.plan.name} has ended",
                f"You're now on {seat.name} through your school or organisation. Everything you made is still here."
                if seat
                else "You're back on the Free plan. Everything you made is still here.",
            )
            sent["ended"] += 1
    return sent
