"""Gift a plan: the buyer pays once; on capture the gift becomes a one-time redeem code (valid a year) emailed to the
recipient, who redeems it through the usual /api/billing/redeem/. A refund is refused once the code is used and voids
it before that."""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from .models import Gift, RedeemCode

log = logging.getLogger(__name__)

GIFT_BATCH = "gift"
CODE_DAYS = 365
MESSAGE_MAX = 300
GIFT_SUBJECT = "You've been gifted an Aasan plan"


class GiftError(ValueError):
    pass


def parse(data, buyer, *, org=None) -> dict | None:
    """Checkout's optional `gift` {recipient_email, message}. None when absent; GiftError(code) when invalid."""
    if not data:
        return None
    if not isinstance(data, dict):
        raise GiftError("bad_gift")
    email = str(data.get("recipient_email") or "").strip().lower()[:254]
    try:
        validate_email(email)
    except ValidationError as e:
        raise GiftError("bad_gift_email") from e
    if email == (buyer.email or "").lower():
        raise GiftError("gift_self")
    if org is not None:
        raise GiftError("gift_org")
    message = " ".join(str(data.get("message") or "").split())[:MESSAGE_MAX]
    return {"recipient_email": email, "message": message}


def _new_code() -> str:
    from .extras import _new_code as make

    while True:
        c = make()
        if not RedeemCode.objects.filter(code=c).exists():
            return c


def fulfil(order) -> Gift:
    """Create the gift's redeem code once (idempotent; grant_for_order already holds the order row) and email it."""
    gift = Gift.objects.select_for_update(of=("self",)).get(order=order)
    if gift.redeem_code_id:
        return gift
    gift.redeem_code = RedeemCode.objects.create(
        code=_new_code(),
        plan=order.plan,
        days=order.plan.period_days,
        batch=GIFT_BATCH,
        expires_at=timezone.now() + timedelta(days=CODE_DAYS),
        created_by=order.user,
    )
    gift.save(update_fields=["redeem_code"])
    gid = gift.pk
    transaction.on_commit(lambda: send(gid))
    return gift


def _buyer_name(user) -> str:
    if not user:
        return "Someone"
    profile = getattr(user, "profile", None)
    return (getattr(profile, "display_name", "") or user.email.split("@")[0])[:80]


def send(gift_id: int) -> bool:
    """Email the code to the recipient. The subject is fixed; the buyer's words only ever go in the body."""
    from django.core.mail import send_mail

    gift = Gift.objects.select_related("order__user__profile", "order__plan", "redeem_code").get(pk=gift_id)
    rc = gift.redeem_code
    if not rc:
        return False
    link = f"{settings.FRONTEND_URL}/plans?code={rc.code}"
    body = (
        f"{_buyer_name(gift.order.user)} has gifted you {rc.plan.name} on Aasan ({rc.days} days of access).\n\n"
        + (f"Their message:\n{gift.message}\n\n" if gift.message else "")
        + f"Your gift code: {rc.code}\nRedeem it here: {link}\n\n"
        f"Sign in or create a free account, then enter the code. It works until "
        f"{timezone.localtime(rc.expires_at):%d %b %Y}."
    )
    try:
        send_mail(GIFT_SUBJECT, body, None, [gift.recipient_email], fail_silently=False)
    except Exception:
        log.warning("gift mail failed for gift %s", gift.pk, exc_info=True)
        return False
    Gift.objects.filter(pk=gift.pk).update(sent_at=timezone.now())
    return True


def on_redeemed(rc: RedeemCode, user) -> None:
    """The recipient used the code: mark it claimed and tell the buyer (after commit)."""
    gift = Gift.objects.filter(redeem_code=rc).select_related("order__user", "order__plan").first()
    if not gift:
        return
    gift.claimed_at = timezone.now()
    gift.save(update_fields=["claimed_at"])
    buyer = gift.order.user
    if not buyer:
        return
    plan_name = rc.plan.name

    def tell():
        from .reminders import _notify

        try:
            _notify(
                buyer, "Your gift is being used", f"{gift.recipient_email} redeemed the {plan_name} you gave."
            )
        except Exception:
            log.exception("gift notice failed")

    transaction.on_commit(tell)


def void_for_refund(order):
    """Inside the refund's order lock: refuse once the gift is redeemed, else void its code. Returns (code_row,
    previous_expiry) so a failed gateway call can restore it, or raises GiftError("gift_redeemed")."""
    gift = Gift.objects.filter(order=order).first()
    if not gift or not gift.redeem_code_id:
        return None, None
    rc = RedeemCode.objects.select_for_update(of=("self",)).get(pk=gift.redeem_code_id)
    if rc.redeemed_at:
        raise GiftError("gift_redeemed")
    before = rc.expires_at
    rc.expires_at = timezone.now()
    rc.save(update_fields=["expires_at"])
    return rc, before
