"""Calendar connect: OAuth app credentials (set by staff) and each learner's read-only connection.
Secrets and refresh tokens are Fernet-encrypted with the same key as provider API keys."""

from django.conf import settings
from django.db import models

from apps.providers import crypto

PROVIDERS = (("google", "Google Calendar"), ("microsoft", "Microsoft Outlook"))


class CalendarApp(models.Model):
    """One row per provider: the OAuth client the owner registered with Google / Microsoft."""

    provider = models.CharField(max_length=16, unique=True, choices=PROVIDERS)
    client_id = models.CharField(max_length=200, blank=True)
    encrypted_secret = models.TextField(blank=True)
    tenant = models.CharField(max_length=64, blank=True)  # Microsoft only; blank = "common"
    enabled = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    def secret(self) -> str:
        return crypto.decrypt(self.encrypted_secret) if self.encrypted_secret else ""


class CalendarConnection(models.Model):
    """A learner's connected calendar. We only ever read free/busy; the refresh token never leaves the server."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="calendar_connections"
    )
    provider = models.CharField(max_length=16, choices=PROVIDERS)
    encrypted_refresh_token = models.TextField()
    scopes = models.CharField(max_length=300, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    needs_reconnect = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "provider"], name="uniq_calendar_per_provider")
        ]

    def set_token(self, token: str) -> None:
        self.encrypted_refresh_token = crypto.encrypt(token)

    def token(self) -> str:
        return crypto.decrypt(self.encrypted_refresh_token) if self.encrypted_refresh_token else ""
