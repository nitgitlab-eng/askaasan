"""Learner: connect / disconnect Google Calendar or Outlook (read-only) and re-plan study blocks around it.
Staff: the OAuth client id / secret per provider and the redirect URIs to register."""

import secrets

from django.core import signing
from django.core.cache import cache
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.staff import AdminSection
from apps.providers import crypto

from . import oauth
from .models import CalendarApp, CalendarConnection
from .services import HORIZON_DAYS, replan

STATE_SALT = "aasan-calendar-oauth"
STATE_MAX_AGE = 600  # seconds the learner has to finish consent


class ConnectThrottle(UserRateThrottle):
    scope = "calendar_connect"
    rate = "20/hour"


class ReplanThrottle(UserRateThrottle):
    scope = "calendar_replan"
    rate = "30/hour"


def _status(user) -> dict:
    conns = {c.provider: c for c in CalendarConnection.objects.filter(user=user)}
    out = []
    for p, spec in oauth.SPEC.items():
        c = conns.get(p)
        out.append(
            {
                "provider": p,
                "label": spec["label"],
                "configured": oauth.app_for(p) is not None,
                "connected": bool(c),
                "connected_at": c.connected_at if c else None,
                "last_synced_at": c.last_synced_at if c else None,
                "needs_reconnect": bool(c and c.needs_reconnect),
            }
        )
    return {"providers": out, "horizon_days": HORIZON_DAYS, "read_only": True}


@api_view(["GET"])
def calendar_status(request):
    return Response(_status(request.user))


@api_view(["POST"])
@throttle_classes([ConnectThrottle])
def connect(request, provider):
    """Start OAuth: returns the provider's consent URL. State is signed, bound to this user, single-use and 10 min long."""
    if provider not in oauth.SPEC:
        return Response(status=status.HTTP_404_NOT_FOUND)
    app = oauth.app_for(provider)
    if not app:
        return Response({"code": "not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    nonce = secrets.token_urlsafe(16)
    verifier, challenge = oauth.pkce_pair()
    cache.set(f"calsync:pkce:{nonce}", {"v": verifier, "u": request.user.id, "p": provider}, STATE_MAX_AGE)
    state = signing.dumps({"u": request.user.id, "p": provider, "n": nonce}, salt=STATE_SALT, compress=True)
    return Response({"url": oauth.authorize_url(app, state, challenge)})


class CallbackIn(serializers.Serializer):
    code = serializers.CharField(max_length=2048)
    state = serializers.CharField(max_length=1024)


@api_view(["POST"])
@throttle_classes([ConnectThrottle])
def callback(request, provider):
    """The web app's /calendar/callback/<provider> page posts the code + state here (with the learner's session)."""
    if provider not in oauth.SPEC:
        return Response(status=status.HTTP_404_NOT_FOUND)
    ser = CallbackIn(data=request.data)
    if not ser.is_valid():
        return Response({"code": "bad_request"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        st = signing.loads(ser.validated_data["state"], salt=STATE_SALT, max_age=STATE_MAX_AGE)
    except signing.BadSignature:  # includes SignatureExpired
        return Response({"code": "bad_state"}, status=status.HTTP_400_BAD_REQUEST)
    if st.get("u") != request.user.id or st.get("p") != provider:
        return Response({"code": "bad_state"}, status=status.HTTP_400_BAD_REQUEST)
    pk = cache.get(f"calsync:pkce:{st.get('n')}")
    cache.delete(f"calsync:pkce:{st.get('n')}")  # single use
    if not pk or pk.get("u") != request.user.id or pk.get("p") != provider:
        return Response({"code": "bad_state"}, status=status.HTTP_400_BAD_REQUEST)
    app = oauth.app_for(provider)
    if not app:
        return Response({"code": "not_configured"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    try:
        tok = oauth.exchange_code(app, ser.validated_data["code"], pk["v"])
    except oauth.CalendarError as e:
        return Response(
            {"code": "exchange_failed" if e.code != "network" else "network"},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    conn = CalendarConnection.objects.filter(
        user=request.user, provider=provider
    ).first() or CalendarConnection(user=request.user, provider=provider)
    conn.set_token(tok["refresh_token"])
    conn.scopes = str(tok.get("scope") or "")[:300]
    conn.needs_reconnect = False
    conn.save()
    return Response(_status(request.user))


@api_view(["DELETE"])
def disconnect(request, provider):
    conn = CalendarConnection.objects.filter(user=request.user, provider=provider).first()
    if not conn:
        return Response(status=status.HTTP_404_NOT_FOUND)
    app = oauth.app_for(provider)
    if app:
        oauth.revoke(app, conn.token())
    conn.delete()
    return Response(_status(request.user))


@api_view(["POST"])
@throttle_classes([ReplanThrottle])
def replan_view(request):
    if not CalendarConnection.objects.filter(user=request.user).exists():
        return Response({"code": "not_connected"}, status=status.HTTP_400_BAD_REQUEST)
    out = replan(request.user)
    return Response({**out, **_status(request.user)})


# ── Staff: OAuth apps ────────────────────────────────────────────────


def _app_out(provider: str) -> dict:
    spec = oauth.SPEC[provider]
    row = CalendarApp.objects.filter(provider=provider).first()
    secret = row.secret() if row and row.encrypted_secret else ""
    env_id, env_secret = spec["env"]
    return {
        "provider": provider,
        "label": spec["label"],
        "client_id": row.client_id if row else "",
        "secret": crypto.mask(secret) if secret else None,
        "tenant": (row.tenant if row else "") or ("common" if provider == "microsoft" else ""),
        "enabled": row.enabled if row else True,
        "ready": oauth.app_for(provider) is not None,
        "redirect_uri": oauth.redirect_uri(provider),
        "scopes": spec["scopes"].split(),
        "console": spec["console"],
        "env_vars": [env_id, env_secret],
        "connections": CalendarConnection.objects.filter(provider=provider).count(),
        "updated_at": row.updated_at if row else None,
    }


class AppPatch(serializers.Serializer):
    client_id = serializers.RegexField(
        r"^[A-Za-z0-9._\-]*$", required=False, allow_blank=True, max_length=200
    )
    # omitted = keep, "" = clear, value = replace
    client_secret = serializers.CharField(
        required=False, allow_blank=True, max_length=512, trim_whitespace=True
    )
    # Microsoft tenant: a well-known alias, a directory GUID or a domain name; it is put into a login URL path.
    tenant = serializers.RegexField(
        r"^(?:common|organizations|consumers"
        r"|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        r"|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})?$",
        required=False,
        allow_blank=True,
        max_length=64,
    )
    enabled = serializers.BooleanField(required=False)


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_apps(request):
    return Response({"apps": [_app_out(p) for p in oauth.SPEC], "read_only": True})


@api_view(["PATCH"])
@permission_classes([AdminSection])
def admin_app(request, provider):
    if provider not in oauth.SPEC:
        return Response(status=status.HTTP_404_NOT_FOUND)
    ser = AppPatch(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    row, _ = CalendarApp.objects.get_or_create(provider=provider)
    if "client_id" in d and d["client_id"] != row.client_id:
        row.client_id = d["client_id"]
        if "client_secret" not in d:
            row.encrypted_secret = ""  # a secret belongs to exactly one client id
    if "client_secret" in d:
        row.encrypted_secret = crypto.encrypt(d["client_secret"]) if d["client_secret"] else ""
    if "tenant" in d and provider == "microsoft":
        row.tenant = d["tenant"]
    if "enabled" in d:
        row.enabled = d["enabled"]
    row.updated_by = request.user
    row.updated_at = timezone.now()
    row.save()
    return Response(_app_out(provider))
