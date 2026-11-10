"""Aasan Companion browser extension: short-lived pairing codes and long-lived device tokens (only the hash is stored)."""

import hashlib

from django.conf import settings
from django.db import models


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ExtensionPairing(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extension_pairings"
    )
    code = models.CharField(max_length=8, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    claimed_at = models.DateTimeField(null=True, blank=True)


class ExtensionToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="extension_tokens"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=120, blank=True)  # derived from the browser's user agent
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)


class ObservedSteps(models.Model):
    """Steps the extension watches for on a browser_task activity (see apps/extension/steps.py). Kept out of
    Activity.source so the Lab's strict source schema keeps working; only the course author can change them."""

    activity = models.OneToOneField(
        "learning.Activity", on_delete=models.CASCADE, related_name="observed_steps"
    )
    steps = models.JSONField(default=list)  # [{id, label, url_pattern, text}]
    # False (default): a submit for this task must carry the observed steps. True: the plain screenshot submit also works.
    optional = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
