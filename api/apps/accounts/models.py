import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from .preferences import default_preferences


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, email_verified=True)
        return self._create(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    google_sub = models.CharField(max_length=64, blank=True, null=True, unique=True)
    # Organisation SSO identity: "<issuer>|<sub>" (apps/orgs/sso.py), linked like google_sub.
    sso_subject = models.CharField(max_length=300, blank=True, null=True, unique=True)
    # Creator Lab access. Granted by admins now; org owners/admins/managers get it in Phase 8.
    is_creator = models.BooleanField(default=False)
    # Consent (DPDP Act 2023): which Terms/Privacy version was accepted, and guardian details for under-18s.
    terms_version = models.CharField(max_length=16, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    age_band = models.CharField(max_length=8, blank=True)  # adult | minor
    guardian_email = models.EmailField(blank=True)
    guardian_nonce = models.CharField(max_length=16, blank=True)  # rotate to revoke the guardian's view link
    guardian_digest = models.BooleanField(default=True)  # weekly progress email to the guardian
    guardian_last_sent = models.DateField(null=True, blank=True)
    # Verifiable consent: set when the guardian clicks "I agree" in the emailed link (apps/accounts/guardian.py).
    # Until then an under-18 can't use AI features (apps/orgs/extras.refusal). Cleared when the guardian changes.
    guardian_consent_at = models.DateTimeField(null=True, blank=True)
    guardian_objected_at = models.DateTimeField(null=True, blank=True)

    @property
    def can_author(self) -> bool:
        if self.is_creator or self.is_staff:
            return True
        from apps.orgs.perms import can_author_via_org

        return can_author_via_org(self)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []
    objects = UserManager()

    def __str__(self):
        return self.email


class Profile(models.Model):
    class Level(models.TextChoices):
        BEGINNER = "beginner"
        INTERMEDIATE = "intermediate"
        ADVANCED = "advanced"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80, blank=True)
    language = models.CharField(
        max_length=8, default="en"
    )  # interface language: en | ta | hi | te | kn | ml | bn | mr | gu
    domain = models.CharField(max_length=64, blank=True)  # e.g. ai, programming, data
    goals = models.JSONField(default=list, blank=True)
    skills = models.JSONField(default=list, blank=True)
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.BEGINNER)
    onboarding_completed = models.BooleanField(default=False)
    avatar = models.JSONField(default=dict, blank=True)
    calendar_nonce = models.CharField(
        max_length=16, blank=True
    )  # rotating secret inside the calendar-feed link
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class UserPreferences(models.Model):
    """All 'make it mine' customisation lives in one versioned JSON document."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    data = models.JSONField(default=default_preferences)
    updated_at = models.DateTimeField(auto_now=True)


class OneTimeToken(models.Model):
    class Purpose(models.TextChoices):
        VERIFY_EMAIL = "verify_email"
        RESET_PASSWORD = "reset_password"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="tokens")
    purpose = models.CharField(max_length=24, choices=Purpose.choices)
    token = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def issue(cls, user, purpose, ttl=timedelta(hours=24)):
        cls.objects.filter(user=user, purpose=purpose, used_at__isnull=True).delete()
        return cls.objects.create(
            user=user,
            purpose=purpose,
            token=secrets.token_urlsafe(32),
            expires_at=timezone.now() + ttl,
        )

    @property
    def is_valid(self):
        return self.used_at is None and self.expires_at > timezone.now()


class PasskeyCredential(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="passkeys")
    credential_id = models.CharField(max_length=512, unique=True)  # base64url
    public_key = models.BinaryField()
    sign_count = models.PositiveIntegerField(default=0)
    transports = models.JSONField(default=list, blank=True)
    name = models.CharField(max_length=64, default="Passkey")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)


class WebAuthnChallenge(models.Model):
    """Short-lived challenge store; keyed by an opaque id handed to the client."""

    key = models.CharField(max_length=64, unique=True)
    challenge = models.BinaryField()
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class StaffRole(models.Model):
    """Which parts of the admin console a staff member may use. A staff user without a row has no admin access
    (superusers always do)."""

    ROLES = ("superadmin", "support", "finance", "content")

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="staff_role")
    roles = models.JSONField(default=list)  # subset of ROLES
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)


class AdminAuditLog(models.Model):
    """Every change made through the admin console: who, what, on which object, from where. Secrets are never stored
    (their values are replaced before saving)."""

    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    actor_email = models.EmailField(blank=True)  # kept if the actor's account is deleted
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=300)
    section = models.CharField(max_length=40, blank=True)
    target = models.CharField(max_length=80, blank=True)  # e.g. "pk=12" from the URL
    data = models.JSONField(default=dict, blank=True)  # request body, secrets masked
    status = models.PositiveSmallIntegerField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    request_id = models.CharField(max_length=64, blank=True)
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-at"]


class PushSubscription(models.Model):
    """One browser/device that accepted web push (the PushSubscription a browser hands out). The endpoint is a
    capability URL on the browser vendor's push service; it is validated against WEBPUSH_ENDPOINT_HOSTS on save and on
    every send."""

    MAX_PER_USER = 10

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.CharField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=64)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)


class WinbackSend(models.Model):
    """One win-back message per learner, kind and lapse episode (the last day they studied, or the day a paid plan
    ended), so reruns and retries never send twice."""

    KINDS = ("inactive_3", "inactive_7", "inactive_30", "plan_lapse", "stepup_1", "stepup_2")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="winback_sends")
    kind = models.CharField(max_length=16)
    episode = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    promo = models.ForeignKey(
        "billing.PromoCode", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "kind", "episode"], name="uniq_winback_episode")
        ]


class ReminderState(models.Model):
    """Per-learner reminder memory (apps/accounts/cadence.py, besttime.py, voice.py): whether the learner picked their
    reminder time, the time they usually start studying (learned nightly), which message variant each moment used
    last, and the back-off state when reminders go unopened."""

    BACKOFF = ("normal", "alternate", "paused")

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="reminder_state")
    time_chosen = models.BooleanField(default=False)  # the learner set learning.reminder_times themselves
    best_minute = models.PositiveSmallIntegerField(null=True, blank=True)  # local minute of day, 0-1439
    best_days = models.PositiveSmallIntegerField(default=0)  # active days the estimate is based on
    best_computed_at = models.DateTimeField(null=True, blank=True)
    last_variants = models.JSONField(default=dict, blank=True)  # moment -> the variant id sent last
    backoff = models.CharField(max_length=10, default="normal")  # normal | alternate | paused
    backoff_since = models.DateTimeField(null=True, blank=True)
    reset_at = models.DateTimeField(
        null=True, blank=True
    )  # last manual resume: ignored pushes count from here
    notice_sent_at = models.DateTimeField(null=True, blank=True)  # the one "we're sending fewer" notice


class PushLog(models.Model):
    """One queued push, with an unguessable token the service worker reports back when it is tapped. Used only to
    send fewer reminders to people who ignore them; pruned after 90 days."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_logs")
    token = models.CharField(max_length=32, unique=True)
    kind = models.CharField(max_length=16)
    moment = models.CharField(max_length=24, blank=True)
    variant = models.CharField(max_length=40, blank=True)
    sent_at = models.DateTimeField(default=timezone.now, db_index=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    opened_via = models.CharField(max_length=8, blank=True)  # push | app

    class Meta:
        indexes = [models.Index(fields=["user", "-sent_at"], name="pushlog_user_sent")]
