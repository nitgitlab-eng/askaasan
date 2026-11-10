from django.conf import settings
from django.contrib.auth import authenticate, password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from . import counters
from .emails import send_password_reset, send_verification
from .models import OneTimeToken, User
from .security_log import security_event
from .serializers import (
    MeSerializer,
    ProfileSerializer,
    RegisterSerializer,
    validate_preferences_patch,
)
from .tokens import clear_refresh_cookie, issue_tokens, refresh_from, revoke_all_sessions, token_response

LOGIN_MAX_FAILS = 10
LOGIN_LOCK_SECONDS = 15 * 60
VERIFY_MAILS_PER_DAY = 5
RESET_MAILS_PER_DAY = 5


def login_locked(email: str) -> bool:
    """Per-account lockout shared by every password entry point (API login and the Django admin form)."""
    return counters.count(f"login-fail:{email}") >= LOGIN_MAX_FAILS


def login_failed(email: str) -> None:
    fails = counters.bump(f"login-fail:{email}", LOGIN_LOCK_SECONDS)
    security_event(
        "account_locked" if fails == LOGIN_MAX_FAILS else "password_failed", email=email, fails=fails
    )


def login_succeeded(email: str) -> None:
    counters.clear(f"login-fail:{email}")
    security_event("password_ok", email=email)


def guard_admin_login(view):
    """Wrap django.contrib.admin's login view so it shares the API login's per-account lockout (no unlimited guessing
    of staff passwords through the HTML form)."""
    from functools import wraps

    from django.http import HttpResponse

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        email = (request.POST.get("username") or "").lower().strip()[:254]
        if login_locked(email):
            return HttpResponse(
                "Too many sign-in attempts. Try again in 15 minutes.", status=429, content_type="text/plain"
            )
        resp = view(request, *args, **kwargs)
        if resp.status_code == 302 and request.user.is_authenticated:
            login_succeeded(email)
        else:
            login_failed(email)
        return resp

    wrapped.lockout_guarded = True
    return wrapped


def mail_allowed(key: str, limit: int, seconds: int = 24 * 3600) -> bool:
    """Count one email against `key`; False once `limit` sends happened in the window (nothing is counted then)."""
    if counters.count(key) >= limit:
        return False
    return counters.bump(key, seconds) <= limit


class AuthThrottle(SimpleRateThrottle):
    scope = "auth"

    def get_cache_key(self, request, view):
        from apps.guests.services import ip_bucket

        # One bucket per IPv6 /64, so rotating addresses inside one allocation doesn't reset the limit.
        return self.cache_format % {"scope": self.scope, "ident": ip_bucket(self.get_ident(request))}


def _sso_refusal(email) -> Response | None:
    """The email's organisation requires its own sign-in (SSO enforced): no password sign-in or sign-up, except for
    that organisation's owners (break-glass). Passkeys never come through here and keep working."""
    from apps.orgs.sso import config_for_email, password_login_allowed

    email = str(email or "").lower().strip()[:254]
    if "@" not in email or password_login_allowed(email):
        return None
    cfg = config_for_email(email)
    return Response(
        {"detail": "sso_required", "org": cfg.org.display_name or cfg.org.name if cfg else ""},
        status=status.HTTP_403_FORBIDDEN,
    )


def _auth_payload(user):
    return {**issue_tokens(user), "user": MeSerializer(user).data}


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def register(request):
    if refused := _sso_refusal(request.data.get("email")):
        return refused
    ser = RegisterSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    user = ser.save()
    send_verification(user)
    return token_response(_auth_payload(user), status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def login(request):
    email = (request.data.get("email") or "").lower().strip()[:254]
    if login_locked(email):  # per-account lockout, independent of IP
        return Response({"detail": "too_many_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if refused := _sso_refusal(email):
        return refused
    user = authenticate(request, email=email, password=request.data.get("password") or "")
    if not user:
        login_failed(email)
        return Response({"detail": "invalid_credentials"}, status=status.HTTP_401_UNAUTHORIZED)
    login_succeeded(email)
    return token_response(_auth_payload(user))


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def refresh(request):
    origin = request.headers.get("Origin")
    if (
        origin and origin not in settings.CSRF_TRUSTED_ORIGINS
    ):  # SameSite=Strict still trusts sibling subdomains
        return Response({"detail": "bad_origin"}, status=status.HTTP_403_FORBIDDEN)
    try:
        token = RefreshToken(refresh_from(request))
        user = User.objects.get(id=token["user_id"], is_active=True)
        token.blacklist()
    except (TokenError, User.DoesNotExist, KeyError):
        return clear_refresh_cookie(
            Response({"detail": "invalid_refresh"}, status=status.HTTP_401_UNAUTHORIZED)
        )
    return token_response(
        issue_tokens(user, auth_time=token.get("auth_time", 0), strong=bool(token.get("strong")))
    )


@api_view(["POST"])
@permission_classes([permissions.AllowAny])  # must work even after the access token expired
def logout(request):
    try:
        RefreshToken(refresh_from(request)).blacklist()
    except TokenError:
        pass
    # This device's push subscription (the endpoint is the device's own capability URL, so knowing it is enough).
    endpoint = request.data.get("push_endpoint") if isinstance(request.data, dict) else None
    if isinstance(endpoint, str) and endpoint:
        from .models import PushSubscription

        PushSubscription.objects.filter(endpoint=endpoint[:1000]).delete()
    return clear_refresh_cookie(Response(status=status.HTTP_204_NO_CONTENT))


@api_view(["GET"])
def me(request):
    return Response(MeSerializer(request.user).data)


@api_view(["PATCH"])
def update_profile(request):
    ser = ProfileSerializer(request.user.profile, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    ser.save()
    return Response(MeSerializer(request.user).data)


@api_view(["GET", "PATCH"])
def preferences(request):
    prefs = request.user.preferences
    if request.method == "PATCH":
        mascot_patch = request.data.get("mascot") or {}
        if "outfit" in mascot_patch or "accessories" in mascot_patch:
            from apps.game.catalog import FREE_ITEMS
            from apps.game.services import stats_for

            owned = FREE_ITEMS | set(stats_for(request.user).owned_items) | {"none"}
            wanted = {mascot_patch.get("outfit", "none"), *(mascot_patch.get("accessories") or [])}
            if not wanted <= owned:
                return Response(
                    {"code": "item_not_owned", "items": sorted(wanted - owned)},
                    status=status.HTTP_403_FORBIDDEN,
                )
        prefs.data = validate_preferences_patch(prefs.data, request.data)
        prefs.save(update_fields=["data", "updated_at"])
        learning = request.data.get("learning") if isinstance(request.data, dict) else None
        if isinstance(learning, dict) and "reminder_times" in learning:
            from .models import ReminderState

            # The learner picked their reminder time: send the study reminder exactly then, not at the learned time.
            ReminderState.objects.update_or_create(user=request.user, defaults={"time_chosen": True})
    return Response(MeSerializer(request.user).data["preferences"])


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def auth_config(request):
    """Public sign-in settings the page needs before anyone is signed in: the Google OAuth client ID (public by design:
    it is embedded in the Google button) and whether any organisation signs in with SSO (shows "Sign in with your
    organisation"). Never anything else from settings, and nothing about which organisations or domains."""
    from apps.orgs.models import OrgSsoConfig

    return Response(
        {
            "google_client_id": settings.GOOGLE_CLIENT_ID or "",
            "sso": OrgSsoConfig.objects.filter(enabled=True).exists(),
        }
    )


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def request_verification(request):
    """Re-sends the verification link. Signed in: to the caller. Signed out (Google sign-in answered
    `account_unverified`): to the unverified account at `email`, if there is one — always 204 in that case, so the
    endpoint can't be used to find out whether an address is registered."""
    if request.user.is_authenticated:
        user = request.user
    else:
        user = User.objects.filter(email=(request.data.get("email") or "").lower(), is_active=True).first()
        if user is None or user.email_verified:
            return Response(status=status.HTTP_204_NO_CONTENT)
    if not user.email_verified:
        # The address was never proven to be theirs, so cap how often we mail it (per account and per recipient).
        if not (
            mail_allowed(f"verify-mail:u{user.id}", VERIFY_MAILS_PER_DAY)
            and mail_allowed(f"verify-mail:{user.email}", VERIFY_MAILS_PER_DAY)
        ):
            if not request.user.is_authenticated:
                return Response(status=status.HTTP_204_NO_CONTENT)
            return Response({"code": "too_many_emails"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        send_verification(user)
    return Response(status=status.HTTP_204_NO_CONTENT)


def _consume(token_str, purpose):
    tok = OneTimeToken.objects.select_related("user").filter(token=token_str or "", purpose=purpose).first()
    if not tok or not tok.is_valid:
        return None
    tok.used_at = timezone.now()
    tok.save(update_fields=["used_at"])
    return tok.user


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@transaction.atomic
def confirm_verification(request):
    user = _consume(request.data.get("token"), OneTimeToken.Purpose.VERIFY_EMAIL)
    if not user:
        return Response({"detail": "invalid_token"}, status=status.HTTP_400_BAD_REQUEST)
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    from apps.game.services import pay_referral

    pay_referral(user)  # referral coins wait until the invited account proves its email
    return Response({"verified": True})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def request_password_reset(request):
    user = User.objects.filter(email=(request.data.get("email") or "").lower(), is_active=True).first()
    # Per-recipient cap on top of the per-IP throttle, so many IPs can't flood one inbox.
    if user and mail_allowed(f"reset-mail:{user.email}", RESET_MAILS_PER_DAY):
        send_password_reset(user)
        security_event("password_reset_requested", user_id=user.pk)
    # Always 204 so the endpoint can't be used to probe which emails exist.
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def verify_password_reset_otp(request):
    """Trade the emailed 6-digit code for a short-lived reset token, which `confirm_password_reset` takes with the new
    password. An unknown email answers like a wrong code, so the endpoint can't probe which emails exist."""
    from .emails import RESET_OTP_TTL, check_reset_otp

    user = User.objects.filter(email=(request.data.get("email") or "").lower(), is_active=True).first()
    code = str(request.data.get("code") or "")
    why = check_reset_otp(user, code) if user and code else "wrong_code"
    if why == "otp_locked":
        security_event("password_reset_otp_locked", user_id=user.pk)
        return Response({"detail": why}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if why:
        return Response({"detail": why}, status=status.HTTP_400_BAD_REQUEST)
    tok = OneTimeToken.issue(user, OneTimeToken.Purpose.RESET_PASSWORD, ttl=RESET_OTP_TTL)
    return Response({"token": tok.token})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@transaction.atomic
def confirm_password_reset(request):
    tok = (
        OneTimeToken.objects.select_related("user")
        .filter(token=request.data.get("token") or "", purpose=OneTimeToken.Purpose.RESET_PASSWORD)
        .first()
    )
    if not tok or not tok.is_valid:
        return Response({"detail": "invalid_token"}, status=status.HTTP_400_BAD_REQUEST)
    password = request.data.get("password") or ""
    try:
        password_validation.validate_password(password, tok.user)
    except DjangoValidationError as e:
        return Response(
            {"detail": "weak_password", "password": e.messages}, status=status.HTTP_400_BAD_REQUEST
        )
    _consume(tok.token, OneTimeToken.Purpose.RESET_PASSWORD)
    tok.user.set_password(password)
    tok.user.email_verified = True  # they proved inbox ownership
    tok.user.save()
    from apps.game.services import pay_referral

    pay_referral(tok.user)  # no-op when already paid
    revoke_all_sessions(tok.user, "password_reset")  # whoever held a session before the reset loses it
    security_event("password_reset", user_id=tok.user.pk)
    return token_response(_auth_payload(tok.user))


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def google_login(request):
    """Verify a Google Identity Services ID token and sign in / sign up."""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    if not settings.GOOGLE_CLIENT_ID:
        return Response({"detail": "google_not_configured"}, status=status.HTTP_501_NOT_IMPLEMENTED)
    try:
        info = id_token.verify_oauth2_token(
            request.data.get("credential") or "", g_requests.Request(), settings.GOOGLE_CLIENT_ID
        )
    except ValueError:
        return Response({"detail": "invalid_google_token"}, status=status.HTTP_401_UNAUTHORIZED)
    if not info.get("email_verified"):
        return Response({"detail": "google_email_unverified"}, status=status.HTTP_401_UNAUTHORIZED)

    from .linking import AccountUnverified, link_or_create

    try:
        user, created = link_or_create(
            info["email"], "google_sub", info["sub"], info.get("name", ""), request.data.get("language")
        )
    except AccountUnverified:
        return Response({"detail": "account_unverified"}, status=status.HTTP_409_CONFLICT)
    security_event("google_login", user_id=user.pk, new_account=created)
    return token_response({**_auth_payload(user), "created": created})


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def unsubscribe_view(request):
    from .notify import unsubscribe

    ok, cat = unsubscribe(str(request.data.get("t") or ""))
    return Response(
        {"ok": ok, "category": cat}, status=status.HTTP_200_OK if ok else status.HTTP_400_BAD_REQUEST
    )
