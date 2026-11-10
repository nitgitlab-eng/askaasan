import secrets

from django.conf import settings
from django.db import models


def _ref_code():
    return secrets.token_urlsafe(6).replace("-", "x").replace("_", "y")[:8].upper()


class PlayerStats(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="game")
    xp = models.PositiveIntegerField(default=0)
    coins = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    best_streak = models.PositiveIntegerField(default=0)
    last_active = models.DateField(null=True, blank=True)
    freezes = models.PositiveSmallIntegerField(default=1)
    owned_items = models.JSONField(default=list, blank=True)
    referral_code = models.CharField(max_length=12, unique=True, default=_ref_code)
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals"
    )
    show_on_leaderboard = models.BooleanField(default=True)
    # Streak repair: the streak that was lost, the day the break was noticed, and when the free revival window began.
    last_streak = models.PositiveIntegerField(default=0)
    broken_at = models.DateField(null=True, blank=True)
    revive_started_at = models.DateTimeField(null=True, blank=True)


class XPEvent(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="xp_events")
    kind = models.CharField(max_length=32)
    xp = models.IntegerField(default=0)
    coins = models.IntegerField(default=0)
    ref = models.CharField(max_length=64, blank=True)  # idempotency key, e.g. "lesson:12"
    day = models.DateField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [models.Index(fields=["user", "kind", "ref"])]
        # award() idempotency key. Shop purchases reuse their item code as ref (a freeze can be bought again).
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "ref"],
                condition=~models.Q(ref="") & ~models.Q(kind="purchase"),
                name="uniq_xpevent_ref",
            )
        ]


class UserBadge(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badges")
    code = models.CharField(max_length=32)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "code"], name="uniq_badge")]


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32)  # badge | level_up | streak | review_due | referral
    title = models.CharField(max_length=160)
    body = models.CharField(max_length=300, blank=True)
    link = models.CharField(max_length=200, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
