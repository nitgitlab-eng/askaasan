"""Enterprise SSO (C1): OpenID Connect sign-in with an organisation's Google Workspace or Microsoft Entra ID, limited to
email domains the organisation proved it owns with a DNS TXT record.

Security model
- Issuer, authorisation, token and JWKS URLs are constants per provider (never discovered from organisation input);
  Microsoft takes a single tenant UUID (no `common` / `organizations`).
- Authorisation code flow with PKCE (S256), a random `state` (single use, cached 600 s) and `nonce` (checked in the ID
  token); the redirect URI is always FRONTEND_URL/sso/callback.
- The ID token's signature (provider JWKS), audience (client ID), issuer, expiry and nonce are verified; Google needs
  `email_verified` and `hd`, Microsoft the configured `tid`. The email's domain must be one of the organisation's
  verified hosted domains. Linking an existing account follows the Google rule (409 `account_unverified`).
- The client secret is encrypted (providers.crypto) and never returned. Enforcement refuses password sign-in and sign-up
  for the domain, except organisation owners (break-glass); passkeys keep working.
- Public mailbox domains and our own host can't be claimed; a daily job re-checks TXT records and un-verifies a domain
  after 7 failing days (dropping enforcement when no verified domain is left)."""

import base64
import hashlib
import hmac
import logging
import re
import secrets
import uuid
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.views import AuthThrottle

from .models import Group, Membership, OrgDomain, OrgSsoConfig
from .perms import RANK, require

log = logging.getLogger(__name__)
STATE_TTL = 600
DNS_CACHE_S = 600
FAILING_DAYS = 7
MAX_DOMAINS = 20
TXT_PREFIX = "aasan-verify="

GOOGLE = {
    "issuers": ("https://accounts.google.com", "accounts.google.com"),
    "auth": "https://accounts.google.com/o/oauth2/v2/auth",
    "token": "https://oauth2.googleapis.com/token",
    "jwks": "https://www.googleapis.com/oauth2/v3/certs",
}
MS_BASE = "https://login.microsoftonline.com"

# Free mailbox providers: anyone can get an address there, so no organisation may claim (or enforce SSO on) them.
PUBLIC_MAILBOXES = frozenset(
    [
        "gmail.com",
        "googlemail.com",
        "outlook.com",
        "outlook.in",
        "hotmail.com",
        "hotmail.co.uk",
        "live.com",
        "live.in",
        "msn.com",
        "yahoo.com",
        "yahoo.co.in",
        "yahoo.in",
        "yahoo.co.uk",
        "ymail.com",
        "rocketmail.com",
        "icloud.com",
        "me.com",
        "mac.com",
        "aol.com",
        "proton.me",
        "protonmail.com",
        "pm.me",
        "zoho.com",
        "zohomail.com",
        "zohomail.in",
        "yandex.com",
        "yandex.ru",
        "mail.com",
        "gmx.com",
        "gmx.net",
        "rediffmail.com",
        "rediff.com",
        "tutanota.com",
        "tuta.io",
        "fastmail.com",
        "hey.com",
        "mail.ru",
        "qq.com",
        "163.com",
        "126.com",
        "sify.com",
        "indiatimes.com",
    ]
)


def endpoints(cfg) -> dict:
    """Fixed per provider. Microsoft URLs embed the (validated UUID) tenant, nothing else from the organisation."""
    if cfg.provider == "microsoft":
        tid = str(uuid.UUID(cfg.tenant_id))
        return {
            "issuers": (f"{MS_BASE}/{tid}/v2.0",),
            "auth": f"{MS_BASE}/{tid}/oauth2/v2.0/authorize",
            "token": f"{MS_BASE}/{tid}/oauth2/v2.0/token",
            "jwks": f"{MS_BASE}/{tid}/discovery/v2.0/keys",
        }
    return GOOGLE


def redirect_uri() -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/sso/callback"


def _domain_of(email: str) -> str:
    return email.rsplit("@", 1)[1].strip().lower() if "@" in email else ""


def normalise_domain(raw: str) -> str | None:
    d = str(raw or "").strip().lower().rstrip(".")
    d = d.removeprefix("@")
    try:
        d = d.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    labels = d.split(".")
    if (
        len(d) > 253
        or len(labels) < 2
        or not all(re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?", x) for x in labels)
    ):
        return None
    if labels[-1].isdigit():
        return None  # an IP address, not a domain
    return d


def _own_domain(d: str) -> bool:
    host = (urlsplit(settings.FRONTEND_URL).hostname or "").lower()
    return bool(host) and (d == host or host.endswith(f".{d}") or d.endswith(f".{host}"))


# ── Who uses SSO ──────────────────────────────────────────────────────


def config_for_email(email: str) -> OrgSsoConfig | None:
    """The enabled SSO configuration that owns this email's domain (verified and listed as a hosted domain)."""
    d = _domain_of(email)
    if not d:
        return None
    dom = OrgDomain.objects.filter(domain=d, verified_at__isnull=False).select_related("org").first()
    if not dom or dom.org.suspended_at:
        return None
    cfg = OrgSsoConfig.objects.filter(org_id=dom.org_id, enabled=True).select_related("org").first()
    return cfg if cfg and d in (cfg.hosted_domains or []) else None


def password_login_allowed(email: str) -> bool:
    """False when the domain enforces SSO, unless this person owns that organisation (break-glass if the IdP breaks).
    Passkeys are not affected (they never pass through here)."""
    cfg = config_for_email(email)
    if not cfg or not cfg.enforced:
        return True
    return Membership.objects.filter(org_id=cfg.org_id, user__email=email.lower(), role="owner").exists()


# ── DNS ───────────────────────────────────────────────────────────────


def txt_records(name: str) -> list[str]:
    """TXT strings for `name` (replaced in tests). Any DNS failure reads as "no records"."""
    import dns.exception
    import dns.resolver

    try:
        answer = dns.resolver.resolve(name, "TXT", lifetime=5)
    except (dns.exception.DNSException, OSError):
        return []
    out = []
    for rr in answer:
        out.append(b"".join(rr.strings).decode("utf-8", "replace"))
    return out


def has_token(dom: OrgDomain, *, cached: bool = True) -> bool:
    want = f"{TXT_PREFIX}{dom.token}"
    found = False
    for name in (dom.domain, f"_aasan.{dom.domain}"):
        key = f"sso-txt:{name}"
        recs = cache.get(key) if cached else None
        if recs is None:
            recs = txt_records(name)
            cache.set(key, recs, DNS_CACHE_S)
        if any(r.strip() == want for r in recs):
            found = True
            break
    return found


def _drop_domain(org_id: int, domain: str) -> None:
    """A domain is no longer verified: take it out of SSO, and stop enforcing when no verified domain is left."""
    cfg = OrgSsoConfig.objects.filter(org_id=org_id).first()
    if not cfg:
        return
    verified = set(
        OrgDomain.objects.filter(org_id=org_id, verified_at__isnull=False).values_list("domain", flat=True)
    )
    cfg.hosted_domains = [d for d in cfg.hosted_domains or [] if d != domain and d in verified]
    if not cfg.hosted_domains:
        cfg.enforced = False
    cfg.save(update_fields=["hosted_domains", "enforced", "updated_at"])


def recheck_domains() -> dict:
    """Daily: verified domains whose TXT record has gone missing for FAILING_DAYS are un-verified."""
    now, kept, dropped = timezone.now(), 0, 0
    for dom in OrgDomain.objects.filter(verified_at__isnull=False):
        if has_token(dom, cached=False):
            dom.last_checked_at, dom.failing_since = now, None
            dom.save(update_fields=["last_checked_at", "failing_since"])
            kept += 1
            continue
        dom.last_checked_at = now
        dom.failing_since = dom.failing_since or now
        if now - dom.failing_since >= timedelta(days=FAILING_DAYS):
            dom.verified_at = None
            dom.save(update_fields=["last_checked_at", "failing_since", "verified_at"])
            _drop_domain(dom.org_id, dom.domain)
            dropped += 1
        else:
            dom.save(update_fields=["last_checked_at", "failing_since"])
    return {"kept": kept, "dropped": dropped}


# ── OIDC ──────────────────────────────────────────────────────────────


class SsoError(Exception):
    def __init__(self, code: str, http: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(code)
        self.code, self.http = code, http


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def authorize_url(cfg: OrgSsoConfig, email: str) -> str:
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    cache.set(
        f"sso-state:{state}",
        {"org": cfg.org_id, "provider": cfg.provider, "nonce": nonce, "verifier": verifier},
        STATE_TTL,
    )
    d = _domain_of(email)
    params = {
        "client_id": cfg.client_id,
        "response_type": "code",
        "scope": "openid email profile",
        "redirect_uri": redirect_uri(),
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "login_hint": email,
    }
    params.update({"hd": d} if cfg.provider == "google" else {"domain_hint": d, "response_mode": "query"})
    return f"{endpoints(cfg)['auth']}?{urlencode(params)}"


def exchange_code(cfg: OrgSsoConfig, code: str, verifier: str) -> str:
    """Authorisation code → ID token at the provider's fixed token endpoint (replaced in tests)."""
    import requests

    from apps.providers.crypto import decrypt

    try:
        r = requests.post(
            endpoints(cfg)["token"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(),
                "client_id": cfg.client_id,
                "client_secret": decrypt(cfg.client_secret_enc),
                "code_verifier": verifier,
            },
            timeout=10,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise SsoError("sso_exchange_failed", status.HTTP_502_BAD_GATEWAY) from None
    if r.status_code != 200:
        raise SsoError("sso_exchange_failed", status.HTTP_401_UNAUTHORIZED)
    token = (r.json() or {}).get("id_token") if "json" in r.headers.get("content-type", "") else None
    if not token:
        raise SsoError("sso_exchange_failed")
    return token


def signing_key(cfg: OrgSsoConfig, token: str):
    """The provider key that signed `token`, from its fixed JWKS URL (replaced in tests)."""
    from jwt import PyJWKClient

    return (
        PyJWKClient(endpoints(cfg)["jwks"], cache_keys=True, timeout=10).get_signing_key_from_jwt(token).key
    )


def verify_id_token(cfg: OrgSsoConfig, token: str, nonce: str) -> dict:
    import jwt

    try:
        key = signing_key(cfg, token)
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=cfg.client_id,
            issuer=list(endpoints(cfg)["issuers"]),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=60,
        )
    except Exception:  # noqa: BLE001 — bad signature, wrong audience/issuer, expired, JWKS unreachable …
        raise SsoError("invalid_sso_token") from None
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise SsoError("invalid_sso_token")
    return claims


def check_claims(cfg: OrgSsoConfig, claims: dict) -> str:
    """→ the verified, allowed email address."""
    email = str(claims.get("email") or "").strip().lower()
    if not email or "@" not in email:
        raise SsoError("sso_email_missing")
    d = _domain_of(email)
    if cfg.provider == "google":
        if claims.get("email_verified") is not True and str(claims.get("email_verified")).lower() != "true":
            raise SsoError("sso_email_unverified")
        if str(claims.get("hd") or "").lower() not in (cfg.hosted_domains or []):
            raise SsoError("sso_domain_not_allowed", status.HTTP_403_FORBIDDEN)
    elif str(claims.get("tid") or "").lower() != cfg.tenant_id.lower():
        raise SsoError("sso_tenant_mismatch", status.HTTP_403_FORBIDDEN)
    verified = OrgDomain.objects.filter(org_id=cfg.org_id, domain=d, verified_at__isnull=False).exists()
    if d not in (cfg.hosted_domains or []) or not verified:
        raise SsoError("sso_domain_not_allowed", status.HTTP_403_FORBIDDEN)
    return email


# ── Public endpoints (/api/users/sso/…) ───────────────────────────────


def _email_in(request) -> str | None:
    email = str(request.data.get("email") or "").strip().lower()[:254]
    return email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) else None


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def lookup(request):
    """{email} → does this email's domain sign in with its organisation? Says nothing about the account."""
    email = _email_in(request)
    if not email:
        return Response({"detail": "bad_email"}, status=status.HTTP_400_BAD_REQUEST)
    cfg = config_for_email(email)
    if not cfg:
        return Response({"sso": False})
    return Response(
        {
            "sso": True,
            "provider": cfg.provider,
            "org": cfg.org.display_name or cfg.org.name,
            "enforced": cfg.enforced,
        }
    )


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def start(request):
    email = _email_in(request)
    if not email:
        return Response({"detail": "bad_email"}, status=status.HTTP_400_BAD_REQUEST)
    cfg = config_for_email(email)
    if not cfg:
        return Response({"detail": "sso_not_configured"}, status=status.HTTP_404_NOT_FOUND)
    return Response({"url": authorize_url(cfg, email)})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def callback(request):
    from apps.accounts.linking import AccountUnverified, link_or_create
    from apps.accounts.tokens import token_response
    from apps.accounts.views import _auth_payload

    from .api import _join

    code, state = str(request.data.get("code") or "")[:2000], str(request.data.get("state") or "")[:200]
    if not code or not state:
        return Response({"detail": "invalid_state"}, status=status.HTTP_400_BAD_REQUEST)
    held = cache.get(f"sso-state:{state}")
    # Single use: the first request to claim the state wins; replays (and parallel duplicates) are refused.
    if not held or not cache.add(f"sso-state-used:{state}", 1, STATE_TTL):
        return Response({"detail": "invalid_state"}, status=status.HTTP_400_BAD_REQUEST)
    cache.delete(f"sso-state:{state}")
    cfg = OrgSsoConfig.objects.filter(org_id=held["org"], enabled=True).select_related("org").first()
    if not cfg or cfg.provider != held["provider"] or cfg.org.suspended_at:
        return Response({"detail": "sso_not_configured"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        claims = verify_id_token(cfg, exchange_code(cfg, code, held["verifier"]), held["nonce"])
        email = check_claims(cfg, claims)
    except SsoError as e:
        log.info("sso sign-in refused for org %s: %s", cfg.org_id, e.code)
        return Response({"detail": e.code}, status=e.http)
    subject = f"{claims['iss']}|{claims['sub']}"[:300]
    try:
        user, created = link_or_create(
            email, "sso_subject", subject, str(claims.get("name") or ""), request.data.get("language")
        )
    except AccountUnverified:  # the IdP just proved this address, so naming it back to the person is safe
        return Response({"detail": "account_unverified", "email": email}, status=status.HTTP_409_CONFLICT)
    if not user.is_active:
        return Response({"detail": "account_disabled"}, status=status.HTTP_403_FORBIDDEN)
    with transaction.atomic():
        _join(
            user,
            cfg.org,
            cfg.default_role if cfg.default_role in ("learner", "manager") else "learner",
            cfg.default_group if cfg.default_group_id else None,
        )
    return token_response({**_auth_payload(user), "created": created, "org": cfg.org.slug})


# ── Organisation settings (/api/orgs/<slug>/sso/…, admins) ────────────


def _domain_out(d: OrgDomain) -> dict:
    return {
        "id": d.id,
        "domain": d.domain,
        "verified": bool(d.verified_at),
        "verified_at": d.verified_at,
        "last_checked_at": d.last_checked_at,
        "failing_since": d.failing_since,
        "txt_name": d.domain,
        "txt_alt_name": f"_aasan.{d.domain}",
        "txt_value": f"{TXT_PREFIX}{d.token}",
    }


def _config_out(org, cfg: OrgSsoConfig | None) -> dict:
    from apps.providers.crypto import decrypt, mask

    secret = ""
    if cfg and cfg.client_secret_enc:
        try:
            secret = mask(decrypt(cfg.client_secret_enc))
        except Exception:  # noqa: BLE001 — a rotated AASAN_SECRETS_KEY: show that one is set, not the error
            secret = "••••"
    return {
        "provider": cfg.provider if cfg else "google",
        "client_id": cfg.client_id if cfg else "",
        "client_secret": secret or None,  # masked; the secret itself is write-only
        "tenant_id": cfg.tenant_id if cfg else "",
        "hosted_domains": cfg.hosted_domains if cfg else [],
        "default_role": cfg.default_role if cfg else "learner",
        "default_group_id": cfg.default_group_id if cfg else None,
        "enabled": bool(cfg and cfg.enabled),
        "enforced": bool(cfg and cfg.enforced),
        "redirect_uri": redirect_uri(),
        "domains": [_domain_out(d) for d in org.domains.all()],
    }


class SsoIn(serializers.Serializer):
    provider = serializers.ChoiceField(choices=["google", "microsoft"], required=False)
    client_id = serializers.CharField(max_length=200, required=False, allow_blank=True)
    client_secret = serializers.CharField(
        max_length=500, required=False, allow_blank=True, trim_whitespace=True
    )
    tenant_id = serializers.CharField(max_length=36, required=False, allow_blank=True)
    hosted_domains = serializers.ListField(
        child=serializers.CharField(max_length=253), required=False, max_length=20
    )
    default_role = serializers.ChoiceField(choices=["learner", "manager"], required=False)
    default_group_id = serializers.IntegerField(required=False, allow_null=True)
    enabled = serializers.BooleanField(required=False)
    enforced = serializers.BooleanField(required=False)


def _bad(code: str, http=status.HTTP_400_BAD_REQUEST):
    return Response({"code": code}, status=http)


@api_view(["GET", "PUT"])
def sso_config(request, slug):
    from apps.providers.crypto import encrypt

    me = require(request.user, slug, "admin")
    org = me.org
    cfg = OrgSsoConfig.objects.filter(org=org).first()
    if request.method == "GET":
        return Response(_config_out(org, cfg))
    ser = SsoIn(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    cfg = cfg or OrgSsoConfig(org=org)
    for f in ("provider", "client_id", "default_role"):
        if f in d:
            setattr(cfg, f, d[f].strip() if isinstance(d[f], str) else d[f])
    if "tenant_id" in d:
        cfg.tenant_id = d["tenant_id"].strip().lower()
    if d.get("client_secret"):
        cfg.client_secret_enc = encrypt(d["client_secret"])
    if cfg.provider == "microsoft":
        try:
            cfg.tenant_id = str(uuid.UUID(cfg.tenant_id))  # a real tenant only: never common/organizations
        except ValueError:
            return _bad("bad_tenant")
    if "hosted_domains" in d:
        wanted = [normalise_domain(x) for x in d["hosted_domains"]]
        verified = set(org.domains.filter(verified_at__isnull=False).values_list("domain", flat=True))
        if any(w is None or w not in verified for w in wanted):
            return _bad("domain_not_verified")
        cfg.hosted_domains = sorted(set(wanted))
    if "default_group_id" in d:
        gid = d["default_group_id"]
        cfg.default_group = get_object_or_404(Group, pk=gid, org=org) if gid else None
    if "enabled" in d:
        cfg.enabled = d["enabled"]
    if "enforced" in d and d["enforced"] != cfg.enforced:
        if d["enforced"] and RANK[me.role] < RANK["owner"]:
            return _bad("owner_only", status.HTTP_403_FORBIDDEN)  # only an owner can lock out passwords
        cfg.enforced = d["enforced"]
    if cfg.enabled and not (cfg.client_id and cfg.client_secret_enc and cfg.hosted_domains):
        return _bad("incomplete")  # client ID, secret and at least one verified domain first
    if not cfg.enabled:
        cfg.enforced = False
    if cfg.enforced and not cfg.hosted_domains:
        return _bad("incomplete")
    cfg.updated_by = request.user
    cfg.save()
    return Response(_config_out(org, cfg))


@api_view(["GET", "POST"])
def sso_domains(request, slug):
    me = require(request.user, slug, "admin")
    org = me.org
    if request.method == "POST":
        d = normalise_domain(request.data.get("domain"))
        if not d:
            return _bad("bad_domain")
        if d in PUBLIC_MAILBOXES:
            return _bad("public_mailbox")
        if _own_domain(d):
            return _bad("own_domain")
        if org.domains.count() >= MAX_DOMAINS:
            return _bad("too_many_domains", status.HTTP_409_CONFLICT)
        if OrgDomain.objects.filter(domain=d, verified_at__isnull=False).exclude(org=org).exists():
            return _bad("domain_taken", status.HTTP_409_CONFLICT)
        dom, _ = OrgDomain.objects.get_or_create(org=org, domain=d, defaults={"created_by": request.user})
        return Response(_domain_out(dom), status=status.HTTP_201_CREATED)
    return Response([_domain_out(x) for x in org.domains.all()])


@api_view(["DELETE"])
def sso_domain_detail(request, slug, pk):
    me = require(request.user, slug, "admin")
    dom = get_object_or_404(OrgDomain, pk=pk, org=me.org)
    domain = dom.domain
    dom.delete()
    _drop_domain(me.org_id, domain)
    return Response(status=status.HTTP_204_NO_CONTENT)


class VerifyThrottle(UserRateThrottle):
    scope, rate = "sso_verify", "20/hour"


@api_view(["POST"])
@throttle_classes([VerifyThrottle])
def sso_domain_verify(request, slug, pk):
    me = require(request.user, slug, "admin")
    dom = get_object_or_404(OrgDomain, pk=pk, org=me.org)
    if dom.verified_at:
        return Response(_domain_out(dom))
    now = timezone.now()
    dom.last_checked_at = now
    if not has_token(dom):
        dom.save(update_fields=["last_checked_at"])
        return Response({"code": "txt_not_found", **_domain_out(dom)}, status=status.HTTP_400_BAD_REQUEST)
    dom.verified_at, dom.failing_since = now, None
    try:
        with transaction.atomic():
            dom.save(update_fields=["last_checked_at", "verified_at", "failing_since"])
    except IntegrityError:  # another organisation verified it first
        return _bad("domain_taken", status.HTTP_409_CONFLICT)
    return Response(_domain_out(dom))


def admin_summary(org) -> dict:
    """For the platform admin console (organisation detail)."""
    cfg = OrgSsoConfig.objects.filter(org=org).first()
    return {
        "provider": cfg.provider if cfg else None,
        "enabled": bool(cfg and cfg.enabled),
        "enforced": bool(cfg and cfg.enforced),
        "hosted_domains": cfg.hosted_domains if cfg else [],
        "domains": [{"domain": d.domain, "verified": bool(d.verified_at)} for d in org.domains.all()],
    }


def admin_disable(org) -> None:
    """Platform support break-glass: switch the organisation's SSO (and its enforcement) off."""
    OrgSsoConfig.objects.filter(org=org).update(enabled=False, enforced=False, updated_at=timezone.now())
