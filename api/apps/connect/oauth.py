"""OAuth 2.1 authorization server for the Aasan MCP endpoint (what Claude's custom connectors expect).

- Metadata: RFC 8414 (authorization server) + RFC 9728 (protected resource).
- Dynamic client registration (RFC 7591): public clients only, redirect URIs https:// or http://localhost.
- Authorization code + PKCE (S256 only). The browser step is the React consent page /connect/authorize, which calls
  `consent` below with the user's normal session; approval is only possible for orgs where the user is admin/owner.
- Tokens: opaque, stored hashed. Access tokens live 1 h and work only on /api/mcp. Refresh tokens rotate on every use;
  presenting a used refresh token (or a used code) revokes the whole grant (token family).
"""

import base64
import hashlib
import hmac
import logging
import re
import secrets
import unicodedata
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_safe
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, BaseThrottle, UserRateThrottle

from apps.guests.services import ip_bucket
from apps.orgs.models import Membership
from apps.orgs.perms import RANK, require

from .models import AuthCode, ConnectAuditLog, Grant, OAuthClient, Token, token_hash

log = logging.getLogger(__name__)

SCOPE = "org:admin"
ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(minutes=5)
MAX_REDIRECTS = 5
CHALLENGE_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
VERIFIER_RE = re.compile(r"^[A-Za-z0-9._~-]{43,128}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f<>]")


# ── URLs ──────────────────────────────────────────────────────────────


def base_url() -> str:
    """Public origin of the site (the web proxy forwards /api/* and /.well-known/oauth-* to Django)."""
    return (getattr(settings, "CONNECT_BASE_URL", "") or settings.FRONTEND_URL).rstrip("/")


def resource_url() -> str:
    return base_url() + "/api/mcp"


def resource_metadata_url() -> str:
    return base_url() + "/api/.well-known/oauth-protected-resource"


def _public_json(data: dict) -> JsonResponse:
    resp = JsonResponse(data)
    resp["Cache-Control"] = "public, max-age=3600"
    resp["Access-Control-Allow-Origin"] = "*"  # public, credential-free documents
    return resp


@require_safe
def authorization_server_metadata(request):
    b = base_url()
    return _public_json(
        {
            "issuer": b,
            "authorization_endpoint": b + "/connect/authorize",
            "token_endpoint": b + "/api/connect/oauth/token",
            "registration_endpoint": b + "/api/connect/oauth/register",
            "revocation_endpoint": b + "/api/connect/oauth/revoke",
            "response_types_supported": ["code"],
            "response_modes_supported": ["query"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "revocation_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": [SCOPE],
            "authorization_response_iss_parameter_supported": True,
            "service_documentation": b + "/connect",
        }
    )


@require_safe
def protected_resource_metadata(request):
    return _public_json(
        {
            "resource": resource_url(),
            "authorization_servers": [base_url()],
            "scopes_supported": [SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_name": "Aasan",
            "resource_documentation": base_url() + "/connect",
        }
    )


# ── Helpers ───────────────────────────────────────────────────────────


def _err(code: str, desc: str = "", http=status.HTTP_400_BAD_REQUEST) -> Response:
    body = {"error": code}
    if desc:
        body["error_description"] = desc
    return Response(body, status=http, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def valid_redirect_uri(u) -> bool:
    if (
        not isinstance(u, str)
        or not u.isascii()
        or not 8 <= len(u) <= 500
        or "#" in u
        or any(c.isspace() for c in u)
        or CONTROL_RE.search(u)
    ):
        return False
    try:
        p = urlsplit(u)
        p.port  # noqa: B018 — raises on a malformed port
    except ValueError:
        return False
    if p.username or p.password or not p.hostname:
        return False
    if p.scheme == "https":
        return True
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1")


def clean_name(v) -> str:
    """Self-declared names are shown on the consent screen: drop control/format characters (bidi overrides,
    zero-width joiners, …) and markup brackets, and collapse whitespace."""
    text = "".join(
        " " if c.isspace() else c for c in str(v or "")[:400] if not unicodedata.category(c).startswith("C")
    )
    name = " ".join(CONTROL_RE.sub("", text).split())[:100]
    return name or "AI assistant"


def _ip_hash(request) -> str:
    ip = BaseThrottle().get_ident(request) or ""
    return hmac.new(settings.SECRET_KEY.encode(), f"connect-ip:{ip}".encode(), hashlib.sha256).hexdigest()


def _pkce_ok(verifier: str, challenge: str) -> bool:
    if not VERIFIER_RE.match(verifier or ""):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(digest, challenge)


def _same_resource(r: str) -> bool:
    return not r or r.rstrip("/") == resource_url()


def is_org_admin(user, org) -> bool:
    m = Membership.objects.filter(org=org, user=user).first()
    return bool(m and user.is_active and RANK.get(m.role, 0) >= RANK["admin"])


def audit_event(event: str, *, org, user=None, client=None, grant=None, detail: str = "") -> None:
    """Connection events in the same log as tool calls (shown on /connect)."""
    client = client or (grant.client if grant else None)
    ConnectAuditLog.objects.create(
        event=event,
        grant=grant,
        client_name=(client.name if client else "")[:100],
        user=user,
        org=org,
        args_summary=detail[:400],
    )


REVOKE_EVENTS = {"user": "revoke", "client": "client_revoke"}


def revoke_grant(grant: Grant, reason: str, by=None) -> None:
    now = timezone.now()
    if Grant.objects.filter(pk=grant.pk, revoked_at__isnull=True).update(
        revoked_at=now, revoked_reason=reason
    ):
        audit_event(REVOKE_EVENTS.get(reason, reason), org=grant.org, user=by or grant.user, grant=grant)
    Token.objects.filter(grant=grant).delete()


def _issue(grant: Grant) -> dict:
    at, rt = "amcp_at_" + secrets.token_urlsafe(32), "amcp_rt_" + secrets.token_urlsafe(32)
    now = timezone.now()
    Token.objects.bulk_create(
        [
            Token(
                grant=grant, kind=Token.Kind.ACCESS, token_hash=token_hash(at), expires_at=now + ACCESS_TTL
            ),
            Token(
                grant=grant, kind=Token.Kind.REFRESH, token_hash=token_hash(rt), expires_at=now + REFRESH_TTL
            ),
        ]
    )
    Token.objects.filter(grant=grant, expires_at__lt=now).delete()  # housekeeping
    return {
        "access_token": at,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
        "refresh_token": rt,
        "scope": grant.scope,
    }


def bearer_grant(request) -> tuple[Grant | None, str]:
    """Access token from the Authorization header → (grant, "") or (None, "missing" | "invalid")."""
    h = request.headers.get("Authorization", "")
    if h[:7].lower() != "bearer ":
        return None, "missing"
    raw = h[7:].strip()
    if not raw.startswith("amcp_at_") or len(raw) > 120:
        return None, "invalid"
    t = (
        Token.objects.select_related("grant__client", "grant__org", "grant__user")
        .filter(token_hash=token_hash(raw), kind=Token.Kind.ACCESS)
        .first()
    )
    if not t or t.expires_at <= timezone.now() or t.grant.revoked_at:
        return None, "invalid"
    if not is_org_admin(t.grant.user, t.grant.org):  # demoted or removed since approving: the connection dies
        revoke_grant(t.grant, "role_lost")
        return None, "invalid"
    return t.grant, ""


# ── Dynamic client registration (RFC 7591) ────────────────────────────


class RegisterThrottle(AnonRateThrottle):
    """Per client IP; IPv6 clients are bucketed by /64 (one host usually owns the whole prefix)."""

    scope = "connect_register"
    rate = "10/hour"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": ip_bucket(self.get_ident(request) or "")}


class RegisterDayThrottle(RegisterThrottle):
    scope = "connect_register_day"
    rate = "30/day"


def _global_register_ok() -> bool:
    """Safety valve only (very high): per-IP / per-/64 throttles are the real limit, so nobody can lock others out."""
    key = f"connect-register:{timezone.localdate()}"
    cache.add(key, 0, 24 * 3600)
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 24 * 3600)
        n = 1
    ceiling = int(getattr(settings, "CONNECT_REGISTRATIONS_CEILING_PER_DAY", 20000))
    if n == ceiling + 1:
        log.warning(
            "Connect Claude: dynamic client registrations passed the daily safety ceiling (%s)", ceiling
        )
    return n <= ceiling


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
@throttle_classes([RegisterThrottle, RegisterDayThrottle])
def register(request):
    d = request.data if isinstance(request.data, dict) else {}
    uris = d.get("redirect_uris")
    if not isinstance(uris, list) or not 1 <= len(uris) <= MAX_REDIRECTS:
        return _err("invalid_redirect_uri", f"redirect_uris: 1 to {MAX_REDIRECTS} URIs")
    if not all(valid_redirect_uri(u) for u in uris):
        return _err("invalid_redirect_uri", "redirect URIs must be https:// or http://localhost")
    grants = d.get("grant_types", ["authorization_code", "refresh_token"])
    if (
        not isinstance(grants, list)
        or not set(grants) <= {"authorization_code", "refresh_token"}
        or "authorization_code" not in grants
    ):
        return _err("invalid_client_metadata", "grant_types: authorization_code (+ refresh_token)")
    responses = d.get("response_types", ["code"])
    if not isinstance(responses, list) or set(responses) != {"code"}:
        return _err("invalid_client_metadata", "response_types: code")
    scope = d.get("scope")
    if scope is not None and (not isinstance(scope, str) or not set(scope.split()) <= {SCOPE}):
        return _err("invalid_client_metadata", "unsupported scope")
    client_uri = d.get("client_uri") or ""
    if client_uri and not (isinstance(client_uri, str) and valid_redirect_uri(client_uri)):
        client_uri = ""
    # Clients registered long ago that nobody ever approved are clutter: drop them.
    OAuthClient.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=7), grants__isnull=True
    ).delete()
    if not _global_register_ok():
        return _err(
            "temporarily_unavailable", "please try again later", http=status.HTTP_429_TOO_MANY_REQUESTS
        )
    c = OAuthClient.objects.create(
        name=clean_name(d.get("client_name")),
        redirect_uris=list(uris),
        client_uri=client_uri,
        ip_hash=_ip_hash(request),
    )
    return Response(
        {
            "client_id": c.client_id,
            "client_id_issued_at": int(c.created_at.timestamp()),
            "client_name": c.name,
            "redirect_uris": c.redirect_uris,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE,
        },
        status=status.HTTP_201_CREATED,
        headers={"Cache-Control": "no-store"},
    )


# ── Authorization (consent API used by the React page) ────────────────


class AuthRequest:
    """Validated /connect/authorize query. `fatal` errors must not redirect (unknown client / redirect URI)."""

    def __init__(self, q):
        self.q = q
        self.client: OAuthClient | None = None
        self.redirect_uri = ""
        self.fatal = ""
        self.error = ""
        self.error_description = ""
        self.state = str(q.get("state") or "")[:500]
        self._validate()

    def _validate(self):
        q = self.q
        self.client = OAuthClient.objects.filter(client_id=str(q.get("client_id") or "")[:64]).first()
        if not self.client:
            self.fatal = "invalid_client"
            return
        ru = str(q.get("redirect_uri") or "")
        if not ru and len(self.client.redirect_uris) == 1:
            ru = self.client.redirect_uris[0]
        if ru not in self.client.redirect_uris:
            self.fatal = "invalid_redirect_uri"
            return
        self.redirect_uri = ru
        if q.get("response_type") != "code":
            self.error, self.error_description = "unsupported_response_type", "response_type must be code"
        elif q.get("code_challenge_method") != "S256" or not CHALLENGE_RE.match(
            str(q.get("code_challenge") or "")
        ):
            self.error, self.error_description = (
                "invalid_request",
                "PKCE with code_challenge_method=S256 is required",
            )
        elif not set(str(q.get("scope") or SCOPE).split()) <= {SCOPE}:
            self.error, self.error_description = "invalid_scope", f"only {SCOPE} is supported"
        elif not _same_resource(str(q.get("resource") or "")):
            self.error, self.error_description = "invalid_target", "unknown resource"

    def redirect(self, **params) -> str:
        params = {k: v for k, v in params.items() if v}
        if self.state:
            params["state"] = self.state
        params["iss"] = base_url()
        sep = "&" if "?" in self.redirect_uri else "?"
        return self.redirect_uri + sep + urlencode(params)


VENDOR_NAME_RE = re.compile(r"claude|anthropic", re.IGNORECASE)
VENDOR_HOSTS = ("claude.ai", "claude.com", "anthropic.com")


def name_mismatch(name: str, host: str | None) -> bool:
    """A self-registered client calling itself Claude/Anthropic but sending the code somewhere else: the consent page
    warns, because the name is chosen by whoever registered the client."""
    host = (host or "").lower().rstrip(".")
    official = any(host == d or host.endswith("." + d) for d in VENDOR_HOSTS)
    return bool(VENDOR_NAME_RE.search(unicodedata.normalize("NFKC", name or ""))) and not official


def _admin_orgs(user):
    ms = (
        Membership.objects.filter(user=user, role__in=("admin", "owner"))
        .select_related("org")
        .order_by("org__name")
    )
    return [{"slug": m.org.slug, "name": m.org.display_name or m.org.name, "role": m.role} for m in ms]


class ConsentThrottle(UserRateThrottle):
    scope = "connect_consent"
    rate = "30/min"


@api_view(["GET", "POST"])
@throttle_classes([ConsentThrottle])
def consent(request):
    """GET: what the consent screen shows. POST {..query.., org, decision}: → {"redirect": url} for the browser.

    Errors never come with an automatic redirect (RFC 9700 §4.11.2: an unapproved client's redirect URI is not
    trusted): invalid client/redirect → error only; other errors → error + the host and a URL the page may offer
    behind an explicit "Return to <host>" button."""
    q = (
        request.query_params
        if request.method == "GET"
        else (request.data if isinstance(request.data, dict) else {})
    )
    ar = AuthRequest(q)
    if ar.fatal:
        return Response({"code": ar.fatal}, status=status.HTTP_400_BAD_REQUEST)
    host = urlsplit(ar.redirect_uri).hostname
    if ar.error:
        return Response(
            {
                "code": ar.error,
                "redirect_host": host,
                "return_url": ar.redirect(error=ar.error, error_description=ar.error_description),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    if request.method == "GET":
        c = ar.client
        return Response(
            {
                "client": {
                    "name": c.name,
                    "redirect_host": host,
                    "redirect_uri": ar.redirect_uri,
                    "registered_at": c.created_at,
                    "new": c.created_at > timezone.now() - timedelta(days=1),
                    "name_mismatch": name_mismatch(c.name, host),
                },
                "scope": SCOPE,
                "orgs": _admin_orgs(request.user),
            }
        )
    decision = q.get("decision")
    slug = str(q.get("org") or "")[:80]
    if decision == "deny":
        m = (
            Membership.objects.select_related("org")
            .filter(user=request.user, org__slug=slug, role__in=("admin", "owner"))
            .first()
        )
        if m:
            audit_event("deny", org=m.org, user=request.user, client=ar.client, detail=f"redirect={host}")
        return Response(
            {"redirect": ar.redirect(error="access_denied", error_description="The user denied the request")}
        )
    if decision != "approve":
        return Response({"code": "bad_decision"}, status=status.HTTP_400_BAD_REQUEST)
    me = require(request.user, slug, "admin")  # 404 non-member, 403 manager/learner
    raw = "amcp_code_" + secrets.token_urlsafe(32)
    AuthCode.objects.create(
        code_hash=token_hash(raw),
        client=ar.client,
        user=request.user,
        org=me.org,
        redirect_uri=ar.redirect_uri,
        redirect_uri_given=bool(q.get("redirect_uri")),
        code_challenge=str(q.get("code_challenge")),
        scope=SCOPE,
        resource=str(q.get("resource") or "")[:300],
        expires_at=timezone.now() + CODE_TTL,
    )
    audit_event("approve", org=me.org, user=request.user, client=ar.client, detail=f"redirect={host}")
    return Response({"redirect": ar.redirect(code=raw)})


# ── Token endpoint ────────────────────────────────────────────────────


class TokenThrottle(AnonRateThrottle):
    scope = "connect_token"
    rate = "60/min"


def _client(d) -> OAuthClient | None:
    return OAuthClient.objects.filter(client_id=str(d.get("client_id") or "")[:64]).first()


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([FormParser, JSONParser])
@throttle_classes([TokenThrottle])
def token(request):
    d = request.data if hasattr(request.data, "get") else {}
    gt = d.get("grant_type")
    if gt not in ("authorization_code", "refresh_token"):
        return _err(
            "unsupported_grant_type" if gt else "invalid_request", "grant_type is required" if not gt else ""
        )
    client = _client(d)
    if not client:
        return _err("invalid_client", "unknown client_id", http=status.HTTP_401_UNAUTHORIZED)
    if not _same_resource(str(d.get("resource") or "")):
        return _err("invalid_target", "unknown resource")
    return _code_exchange(d, client) if gt == "authorization_code" else _refresh(d, client)


def _code_exchange(d, client) -> Response:
    raw = str(d.get("code") or "")
    if not raw or len(raw) > 120:
        return _err("invalid_request", "code is required")
    with transaction.atomic():
        code = (
            AuthCode.objects.select_for_update(of=("self",))
            .select_related("org", "user", "grant")
            .filter(code_hash=token_hash(raw))
            .first()
        )
        if not code or code.client_id != client.id:
            return _err("invalid_grant")
        if code.used_at:  # replay: whatever was issued from this code is presumed stolen
            if code.grant:
                revoke_grant(code.grant, "code_reuse")
            return _err("invalid_grant", "code already used")
        code.used_at = timezone.now()
        code.save(update_fields=["used_at"])
        if code.expires_at <= timezone.now():
            return _err("invalid_grant", "code expired")
        ru = d.get("redirect_uri")
        if (
            code.redirect_uri_given or ru
        ) and ru != code.redirect_uri:  # required (and exact) if it was in the request
            return _err("invalid_grant", "redirect_uri mismatch")
        res = str(d.get("resource") or "")
        if res and code.resource and res.rstrip("/") != code.resource.rstrip("/"):
            return _err("invalid_target", "resource differs from the authorization request")
        if not _pkce_ok(str(d.get("code_verifier") or ""), code.code_challenge):
            return _err("invalid_grant", "PKCE verification failed")
        if not is_org_admin(code.user, code.org):
            return _err("invalid_grant", "approval no longer valid")
        grant = Grant.objects.create(client=client, user=code.user, org=code.org, scope=code.scope)
        code.grant = grant
        code.save(update_fields=["grant"])
        audit_event("code_exchange", org=code.org, user=code.user, grant=grant)
        out = _issue(grant)
    return Response(out, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def _refresh(d, client) -> Response:
    raw = str(d.get("refresh_token") or "")
    if not raw.startswith("amcp_rt_") or len(raw) > 120:
        return _err("invalid_request" if not raw else "invalid_grant")
    scope = d.get("scope")
    if scope and not set(str(scope).split()) <= {SCOPE}:
        return _err("invalid_scope")
    with transaction.atomic():
        t = (
            Token.objects.select_for_update(of=("self",))
            .select_related("grant__user", "grant__org")
            .filter(token_hash=token_hash(raw), kind=Token.Kind.REFRESH)
            .first()
        )
        if not t or t.grant.client_id != client.id or t.grant.revoked_at:
            return _err("invalid_grant")
        grant = t.grant
        if t.used_at:  # a rotated refresh token came back: someone kept a copy → kill the whole family
            revoke_grant(grant, "refresh_reuse")
            return _err("invalid_grant", "refresh token reused; connection revoked")
        if t.expires_at <= timezone.now():
            return _err("invalid_grant", "refresh token expired")
        if not is_org_admin(grant.user, grant.org):
            revoke_grant(grant, "role_lost")
            return _err("invalid_grant")
        t.used_at = timezone.now()
        t.save(update_fields=["used_at"])
        out = _issue(grant)
    return Response(out, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


# ── Revocation (RFC 7009) ─────────────────────────────────────────────


class RevokeThrottle(AnonRateThrottle):
    scope = "connect_revoke"
    rate = "30/min"


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@parser_classes([FormParser, JSONParser])
@throttle_classes([RevokeThrottle])
def revoke(request):
    d = request.data if hasattr(request.data, "get") else {}
    raw = str(d.get("token") or "")
    if not raw or len(raw) > 120:
        return _err("invalid_request", "token is required")
    client = _client(d)
    if not client:
        return _err("invalid_client", http=status.HTTP_401_UNAUTHORIZED)
    t = Token.objects.select_related("grant").filter(token_hash=token_hash(raw), grant__client=client).first()
    if t:
        if t.kind == Token.Kind.REFRESH:
            revoke_grant(t.grant, "client")
        else:
            t.delete()
    return Response(
        status=status.HTTP_200_OK, headers={"Cache-Control": "no-store"}
    )  # same answer for unknown tokens
