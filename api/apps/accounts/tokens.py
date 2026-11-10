"""JWT issuing. The 30-day refresh token lives ONLY in an HttpOnly cookie (never in JSON or localStorage),
so a script injected into the page can't steal a long-lived session. The short access token is returned in JSON."""

import logging
import time
from datetime import timedelta

from django.conf import settings
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

COOKIE = "aasan_refresh"
COOKIE_PATH = "/api/users/"  # only sent to refresh / logout


REAUTH_SECONDS = 10 * 60  # how long a sign-in counts as "recent" for sensitive changes (adding a passkey)


def issue_tokens(user, auth_time: int | None = None, strong: bool = False) -> dict:
    """`auth_time` is when the person last proved who they are (password, passkey, Google, email code). A fresh
    sign-in stamps now; a refresh carries the old value forward, so a stolen session can't make itself "recent".
    `strong`: that proof was a passkey or an emailed code, not a password alone (staff admin changes need it)."""
    refresh = RefreshToken.for_user(user)
    refresh["auth_time"] = int(time.time()) if auth_time is None else int(auth_time)
    refresh["strong"] = bool(strong)
    touch_last_seen(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


LAST_SEEN_EVERY = timedelta(hours=1)


def touch_last_seen(user) -> None:
    """Record when the person last used the app (sign-in, passkey, sign-up or a token refresh) in `last_login`, which
    the admin console shows as "Last seen". At most one write an hour per person, so refreshes stay cheap."""
    from django.utils import timezone

    from .models import User

    now = timezone.now()
    User.objects.filter(pk=user.pk).exclude(last_login__gte=now - LAST_SEEN_EVERY).update(last_login=now)
    try:  # opening the app soon after a reminder counts as opening the reminder (cadence.py)
        from django.db import transaction

        from .cadence import mark_app_visit

        with transaction.atomic():  # a savepoint: a failure here never spoils the caller's transaction
            mark_app_visit(user, now)
    except Exception:
        logging.getLogger(__name__).exception("tokens: marking pushes opened for user %s failed", user.pk)


def recently_authenticated(request, within: int = REAUTH_SECONDS) -> bool:
    from rest_framework_simplejwt.tokens import Token

    tok = request.auth
    return isinstance(tok, Token) and time.time() - int(tok.get("auth_time", 0) or 0) <= within


def strongly_authenticated(request) -> bool:
    from rest_framework_simplejwt.tokens import Token

    return isinstance(request.auth, Token) and bool(request.auth.get("strong"))


def set_refresh_cookie(resp, token: str):
    resp.set_cookie(
        COOKIE,
        token,
        max_age=int(timedelta(days=30).total_seconds()),
        httponly=True,
        secure=not settings.DEBUG,
        samesite="Strict",
        path=COOKIE_PATH,
    )
    return resp


def clear_refresh_cookie(resp):
    resp.delete_cookie(COOKIE, path=COOKIE_PATH, samesite="Strict")
    return resp


def token_response(payload: dict, status: int = 200) -> Response:
    """Response with the access token (+ any extra fields) in JSON and the refresh token as a cookie."""
    body = dict(payload)
    refresh = body.pop("refresh")
    return set_refresh_cookie(Response(body, status=status), refresh)


def refresh_from(request) -> str:
    # Body fallback lets browsers that still hold a pre-cookie token migrate once (see web/src/lib/api.ts).
    return (
        request.COOKIES.get(COOKIE) or (request.data.get("refresh") if hasattr(request, "data") else "") or ""
    )


def revoke_all_sessions(user, reason: str) -> None:
    """End every existing credential except the password: refresh tokens, extension devices, Connect grants and
    passkeys. Used when account ownership is re-established (password reset) so an earlier compromise does not survive
    it (e.g. a squatter who registered the address first and enrolled their own passkey)."""
    from django.utils import timezone
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

    from apps.connect.models import Grant
    from apps.connect.oauth import revoke_grant
    from apps.extension.models import ExtensionToken

    from .models import PasskeyCredential, PushSubscription

    PushSubscription.objects.filter(user=user).delete()  # devices signed in before stop getting notifications
    for tok in OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False):
        BlacklistedToken.objects.get_or_create(token=tok)
    ExtensionToken.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())
    PasskeyCredential.objects.filter(user=user).delete()
    for g in Grant.objects.filter(user=user, revoked_at__isnull=True):
        revoke_grant(g, reason)
