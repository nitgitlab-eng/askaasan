from django.conf import settings
from django.db import models

from apps.providers import crypto

# Limits a plan can set. A missing or null value means unlimited.
LIMIT_KEYS = (
    "ai_courses_per_month",
    "mentor_messages_per_day",
    "documents",
    "voice_minutes_per_day",
    "tts_chars_per_day",
    "live_minutes_per_day",
    "lab_ai_per_day",
)


class PaymentConfig(models.Model):
    """Singleton (pk=1): Razorpay keys set from the Aasan admin console. Secrets are Fernet-encrypted."""

    key_id = models.CharField(max_length=64, blank=True)
    encrypted_secret = models.TextField(blank=True)
    encrypted_webhook_secret = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    allow_live = models.BooleanField(default=False)  # live keys are refused until a super admin flips this
    business_name = models.CharField(max_length=80, default="Aasan")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def _dec(v: str) -> str:
        return crypto.decrypt(v) if v else ""

    def secret(self) -> str:
        return self._dec(self.encrypted_secret)

    def webhook_secret(self) -> str:
        return self._dec(self.encrypted_webhook_secret)


class Plan(models.Model):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240, blank=True)
    price_paise = models.PositiveIntegerField(default=0)  # GST-inclusive price in paise
    period_days = models.PositiveIntegerField(default=30)  # access granted per payment; 0 for the free plan
    limits = models.JSONField(default=dict, blank=True)
    badge = models.CharField(max_length=40, blank=True)  # e.g. "2 months free"
    active = models.BooleanField(default=True)
    sort = models.PositiveSmallIntegerField(default=0)
    # Recurring billing (Razorpay Subscriptions): the matching plan_… id from Razorpay Dashboard, and whether to offer it.
    rp_plan_id = models.CharField(max_length=40, blank=True)
    auto_renew = models.BooleanField(default=False)
    # Family plan: the buyer shares the plan with up to max_members people in all (the buyer counts).
    family = models.BooleanField(default=False)
    max_members = models.PositiveSmallIntegerField(default=5)

    class Meta:
        ordering = ["sort", "price_paise"]

    @property
    def is_free(self) -> bool:
        return self.price_paise == 0


class Order(models.Model):
    class Status(models.TextChoices):
        CREATED = "created"
        PAID = "paid"
        FAILED = "failed"

    # Kept (without the person) when an account is deleted — tax records.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="orders"
    )
    plan = models.ForeignKey(Plan, null=True, blank=True, on_delete=models.PROTECT)  # null: a workshop seat
    # A paid public workshop seat (apps.workshops): granted as a WorkshopEnrollment on capture, not an Entitlement.
    workshop_run = models.ForeignKey(
        "workshops.WorkshopRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default="INR")
    rp_order_id = models.CharField(max_length=64, unique=True)
    rp_payment_id = models.CharField(max_length=64, blank=True)
    mode = models.CharField(max_length=4, default="test")  # test | live
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.CREATED)
    error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    # Milestone 5: org seat purchases, promo codes, GST buyer details
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    seats = models.PositiveIntegerField(default=1)
    list_paise = models.PositiveIntegerField(default=0)  # before discount
    promo = models.ForeignKey(
        "PromoCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    discount_paise = models.PositiveIntegerField(default=0)
    buyer_name = models.CharField(max_length=160, blank=True)
    buyer_gstin = models.CharField(max_length=15, blank=True)
    buyer_state = models.CharField(max_length=40, blank=True)
    subscription = models.ForeignKey(
        "Subscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="charges"
    )

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_gift(self) -> bool:
        from django.core.exceptions import ObjectDoesNotExist

        try:
            return self.gift is not None
        except ObjectDoesNotExist:
            return False

    @property
    def label(self) -> str:
        """What was bought, for lists, receipts and invoices."""
        if self.plan_id:
            return f"Gift: {self.plan.name}" if self.is_gift else self.plan.name
        run = self.workshop_run
        if run:
            from django.utils import timezone

            return f"Workshop: {run.workshop.title}, {timezone.localtime(run.starts_at):%d %b %Y}"
        return "Workshop"


class Entitlement(models.Model):
    """A window of access to a paid plan — from a payment or a manual grant by a super admin."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="entitlements")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    order = models.OneToOneField(
        Order, null=True, blank=True, on_delete=models.SET_NULL
    )  # one grant per payment
    source = models.CharField(
        max_length=8, default="payment"
    )  # payment | grant | redeem | grace | family | gift
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    note = models.CharField(max_length=200, blank=True)
    reminded_soon_at = models.DateTimeField(null=True, blank=True)  # "ends in 3 days"
    reminded_end_at = models.DateTimeField(null=True, blank=True)  # "has ended"
    created_at = models.DateTimeField(auto_now_add=True)
    # Family plan members get a mirror (source="family") of each of the owner's family-plan windows.
    family_group = models.ForeignKey(
        "FamilyGroup", null=True, blank=True, on_delete=models.CASCADE, related_name="mirrors"
    )
    derived_from = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="mirrors"
    )

    class Meta:
        ordering = ["-ends_at"]
        constraints = [
            models.UniqueConstraint(fields=["derived_from", "user"], name="uniq_family_mirror"),
        ]


class UsageEvent(models.Model):
    """Metered actions that aren't otherwise countable from the DB (e.g. AI course generations)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    metric = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "metric", "created_at"])]


class PromoCode(models.Model):
    """Discount at checkout: percent or fixed, optional plan list, expiry and use cap. Uses count only on payment."""

    code = models.CharField(max_length=32, unique=True)  # stored upper-case
    kind = models.CharField(max_length=8, default="percent")  # percent | fixed
    value = models.PositiveIntegerField()  # percent (1–100) or paise
    plans = models.JSONField(default=list, blank=True)  # plan codes; [] = all paid plans
    expires_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(default=0)  # 0 = unlimited
    uses = models.PositiveIntegerField(default=0)
    per_user = models.PositiveSmallIntegerField(default=1)
    max_seats = models.PositiveIntegerField(
        default=0
    )  # school seat purchases: 0 = not allowed, else the most seats per order
    active = models.BooleanField(default=True)
    note = models.CharField(max_length=160, blank=True)
    # "winback_lapse": the code the win-back job emails to learners whose paid plan ended (newest active one is used).
    purpose = models.CharField(
        max_length=16,
        blank=True,
        default="",
        choices=[("", "Any checkout"), ("winback_lapse", "Win-back after a plan ends")],
    )
    created_at = models.DateTimeField(auto_now_add=True)


class RedeemCode(models.Model):
    """Prepaid access a school/partner hands out: one code = one person gets `plan` for `days`."""

    code = models.CharField(max_length=24, unique=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    days = models.PositiveIntegerField(default=30)
    batch = models.CharField(max_length=80, blank=True)
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="redeem_codes"
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    redeemed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    redeemed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class OrgSubscription(models.Model):
    """Seats an org paid for: members holding a seat get `plan` until `ends_at`."""

    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    seats = models.PositiveIntegerField()
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    order = models.OneToOneField(Order, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)


class Invoice(models.Model):
    """GST tax invoice for one paid order. Numbered per Indian financial year; amounts frozen at issue."""

    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="invoice")
    number = models.CharField(max_length=32, unique=True)
    fy = models.CharField(max_length=7)  # e.g. 2026-27
    seq = models.PositiveIntegerField()
    issued_at = models.DateTimeField(auto_now_add=True)
    seller = models.JSONField()  # name, address, gstin, state — copied from Site & legal at issue time
    buyer = models.JSONField()  # name, email, gstin, state
    taxable_paise = models.PositiveIntegerField()
    cgst_paise = models.PositiveIntegerField(default=0)
    sgst_paise = models.PositiveIntegerField(default=0)
    igst_paise = models.PositiveIntegerField(default=0)
    total_paise = models.PositiveIntegerField()
    lines = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["fy", "seq"], name="uniq_invoice_seq")]


class Subscription(models.Model):
    """Auto-renew via Razorpay Subscriptions. Each successful charge becomes a paid Order (entitlement + GST invoice)."""

    LIVE = (
        "authenticated",
        "active",
        "pending",
        "halted",
        "paused",
    )  # states that still bill or may bill again

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="subscriptions"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT)
    rp_subscription_id = models.CharField(max_length=64, unique=True)
    mode = models.CharField(max_length=4, default="test")
    # created | authenticated | active | pending | halted | paused | cancelled | completed | expired
    status = models.CharField(max_length=16, default="created")
    amount_paise = models.PositiveIntegerField(default=0)
    current_start = models.DateTimeField(null=True, blank=True)
    current_end = models.DateTimeField(null=True, blank=True)
    charge_at = models.DateTimeField(null=True, blank=True)  # next charge
    paid_count = models.PositiveIntegerField(default=0)
    cancel_at_period_end = models.BooleanField(default=False)
    method = models.CharField(max_length=60, blank=True)  # masked: "Visa •••• 4242", "ka•••@okhdfc"
    grace_until = models.DateTimeField(null=True, blank=True)  # set once while halted
    ended_at = models.DateTimeField(null=True, blank=True)
    buyer_name = models.CharField(max_length=160, blank=True)
    buyer_gstin = models.CharField(max_length=15, blank=True)
    buyer_state = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class WebhookEvent(models.Model):
    """Razorpay event ids we've processed, so retries and duplicates are no-ops."""

    event_id = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=48)
    received_at = models.DateTimeField(auto_now_add=True)


class Refund(models.Model):
    """Money sent back for a paid order, through Razorpay. Status follows Razorpay (webhook refund.processed/failed)."""

    class Status(models.TextChoices):
        PENDING = "pending"
        PROCESSED = "processed"
        FAILED = "failed"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="refunds")
    amount_paise = models.PositiveIntegerField()
    reason = models.CharField(max_length=200)
    rp_refund_id = models.CharField(max_length=40, blank=True, db_index=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=240, blank=True)
    access_ended = models.BooleanField(default=False)  # the plan bought with this order was ended
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class FamilyGroup(models.Model):
    """The people one family-plan buyer shares their plan with. Created when the owner first invites someone."""

    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="family_owned"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class FamilyMember(models.Model):
    """A seat in a family (the owner holds one too). left_at set = gone; one active family per person."""

    group = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="family_memberships"
    )
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["joined_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(left_at__isnull=True), name="one_active_family"
            ),
        ]


class FamilyInvite(models.Model):
    """An invitation bound to one email address. The link token and the short code are stored only as hashes."""

    group = models.ForeignKey(FamilyGroup, on_delete=models.CASCADE, related_name="invites")
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    code_hash = models.CharField(max_length=64, db_index=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Gift(models.Model):
    """A plan bought for someone else: on payment it becomes a one-time redeem code emailed to the recipient."""

    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="gift")
    recipient_email = models.EmailField()
    message = models.CharField(max_length=300, blank=True)
    redeem_code = models.OneToOneField(
        RedeemCode, null=True, blank=True, on_delete=models.SET_NULL, related_name="gift"
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
