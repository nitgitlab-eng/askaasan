"""Connect Claude: OAuth 2.1 clients/grants/tokens for the remote MCP server, and an audit log of every tool call.

Tokens are opaque random strings; only their SHA-256 hash is stored. A Grant is one approved connection
(client + user + one org); its refresh tokens form a single rotation family — revoking the grant kills them all."""

import hashlib
import secrets

from django.conf import settings
from django.db import models


def token_hash(raw: str) -> str:
    return hashlib.sha256(f"aasan-connect:{raw}".encode()).hexdigest()


def _client_id():
    return "aasan_c_" + secrets.token_urlsafe(18)


class OAuthClient(models.Model):
    """A dynamically registered public client (RFC 7591). The name is self-declared: never trusted, only shown."""

    client_id = models.CharField(max_length=64, unique=True, default=_client_id)
    name = models.CharField(max_length=100)
    redirect_uris = models.JSONField(default=list)
    client_uri = models.CharField(max_length=300, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Grant(models.Model):
    """One approved connection: this client may act for this user, scoped to this one org (scope org:admin)."""

    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="grants")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=40, default="org:admin")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(
        max_length=24, blank=True
    )  # user | refresh_reuse | code_reuse | role_lost

    class Meta:
        ordering = ["-created_at"]


class AuthCode(models.Model):
    """Single-use authorization code (PKCE S256). Exchanging it creates the Grant; reuse revokes that grant."""

    code_hash = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(OAuthClient, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="+")
    redirect_uri = models.CharField(max_length=500)
    redirect_uri_given = models.BooleanField(
        default=True
    )  # sent in the authorize request → must be repeated exactly
    code_challenge = models.CharField(max_length=128)
    scope = models.CharField(max_length=40, default="org:admin")
    resource = models.CharField(max_length=300, blank=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    grant = models.ForeignKey(Grant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)


class Token(models.Model):
    class Kind(models.TextChoices):
        ACCESS = "access"
        REFRESH = "refresh"

    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="tokens")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)  # refresh tokens: rotated (single use)
    created_at = models.DateTimeField(auto_now_add=True)


class ConnectAuditLog(models.Model):
    """Every MCP tool call (who, which org, which tool, a short argument summary) plus connection events (approvals,
    denials, code exchanges, revocations)."""

    grant = models.ForeignKey(Grant, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit")
    client_name = models.CharField(max_length=100)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="+")
    # tool (an MCP tool call) | approve | deny | code_exchange | code_reuse | refresh_reuse | role_lost | revoke | client_revoke
    event = models.CharField(max_length=16, default="tool")
    tool = models.CharField(max_length=40, blank=True)
    args_summary = models.CharField(max_length=400, blank=True)
    ok = models.BooleanField(default=True)
    error = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at", "-id"]
