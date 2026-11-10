"""API-key authentication for /api/v1/ (and only there).

`Authorization: Bearer ak_…`: the key is looked up by its SHA-256 (the raw key is never stored), revoked keys and keys of
suspended organisations are refused. /api/v1/ views use ApiKeyAuthentication alone, so a user's JWT is refused there;
every other route uses JWT authentication, which rejects an `ak_…` bearer as an invalid token."""

from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.throttling import SimpleRateThrottle

from .models import OrgApiKey, hash_key

TOUCH_EVERY = timedelta(minutes=1)


class KeyPrincipal:
    """request.user for an API-key request: authenticated, but no person and no staff powers."""

    is_authenticated = True
    is_anonymous = False
    is_active = True
    is_staff = False
    is_superuser = False
    pk = id = None

    def __init__(self, key: OrgApiKey):
        self.key = key

    def __str__(self):
        return f"api-key:{self.key.prefix}"


class ApiKeyAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2:
            raise AuthenticationFailed("invalid_api_key")
        raw = parts[1].decode("latin-1")
        if not raw.startswith("ak_") or len(raw) > 100:
            raise AuthenticationFailed("invalid_api_key")  # e.g. a user's JWT: never accepted here
        key = (
            OrgApiKey.objects.select_related("org")
            .filter(key_hash=hash_key(raw), revoked_at__isnull=True)
            .first()
        )
        if not key:
            raise AuthenticationFailed("invalid_api_key")
        if key.org.suspended_at:
            raise PermissionDenied("org_suspended")
        now = timezone.now()
        if not key.last_used_at or now - key.last_used_at > TOUCH_EVERY:  # at most one write a minute
            OrgApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
        return KeyPrincipal(key), key

    def authenticate_header(self, request):
        return 'Bearer realm="api"'


def scoped(scope: str):
    """Permission: an API key with `scope`, for the organisation named in the URL (another org's slug is a 404)."""

    class HasScope(BasePermission):
        def has_permission(self, request, view):
            key = request.auth
            if not isinstance(key, OrgApiKey):
                return False
            if view.kwargs.get("slug") != key.org.slug:
                raise Http404
            if scope not in (key.scopes or []):
                raise PermissionDenied("missing_scope")
            return True

    return HasScope


class ApiKeyThrottle(SimpleRateThrottle):
    """Per key, API_KEY_RATE (default 600/hour)."""

    scope = "api_key"

    def get_rate(self):
        return getattr(settings, "API_KEY_RATE", "600/hour")

    def get_cache_key(self, request, view):
        key = request.auth
        return (
            self.cache_format % {"scope": self.scope, "ident": key.id} if isinstance(key, OrgApiKey) else None
        )
