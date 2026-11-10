"""Organisation API keys (read progress / members, invite or remove learners over /api/v1/) and outbound webhooks."""

import hashlib
import secrets

from django.conf import settings
from django.db import models

SCOPES = ("read:progress", "read:members", "write:members")
EVENTS = (
    "member.joined",
    "assignment.completed",
    "course.completed",
    "certificate.issued",
    "workshop.passed",
)
KEY_ALPHABET = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/l/I look-alikes


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_raw_key() -> str:
    """`ak_` + 40 random characters (~230 bits). Only its SHA-256 is stored; the first 11 characters are the prefix
    shown in lists so admins can tell keys apart."""
    return "ak_" + "".join(secrets.choice(KEY_ALPHABET) for _ in range(40))


class OrgApiKey(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=80)
    prefix = models.CharField(max_length=11)  # "ak_" + 8
    key_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)  # ⊆ SCOPES
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class OrgWebhook(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="webhooks")
    url = models.CharField(max_length=500)  # https only, vetted with safe_fetch on save and on every delivery
    secret_enc = models.TextField()  # providers.crypto (shown once, at creation or rotation)
    events = models.JSONField(default=list)  # ⊆ EVENTS
    active = models.BooleanField(default=True)
    failures = models.PositiveIntegerField(default=0)  # consecutive dead deliveries (auto-disable at 20)
    disabled_reason = models.CharField(max_length=40, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class WebhookDelivery(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        OK = "ok"
        FAILED = "failed"  # will be retried at next_try_at
        DEAD = "dead"  # gave up (refused URL, or every try failed)

    webhook = models.ForeignKey(OrgWebhook, on_delete=models.CASCADE, related_name="deliveries")
    event = models.CharField(max_length=40)
    payload = models.JSONField()  # {id, event, created_at, org, data}: first names only, never emails
    attempt = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=200, blank=True)
    next_try_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "next_try_at"], name="intg_delivery_due")]
