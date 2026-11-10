"""WebAuthn passkey registration + passwordless login (py_webauthn)."""

import secrets

from django.conf import settings
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.response import Response
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .models import PasskeyCredential, WebAuthnChallenge
from .security_log import security_event
from .serializers import MeSerializer
from .tokens import issue_tokens, recently_authenticated, refresh_from, token_response
from .views import AuthThrottle, login_failed, login_locked, login_succeeded

CHALLENGE_TTL_SECONDS = 300


def _store(challenge: bytes, user=None) -> str:
    WebAuthnChallenge.objects.filter(
        created_at__lt=timezone.now() - timezone.timedelta(seconds=CHALLENGE_TTL_SECONDS)
    ).delete()
    key = secrets.token_urlsafe(24)
    WebAuthnChallenge.objects.create(key=key, challenge=challenge, user=user)
    return key


def _pop(key: str):
    row = WebAuthnChallenge.objects.filter(key=key or "").first()
    if not row:
        return None
    row.delete()
    if row.created_at < timezone.now() - timezone.timedelta(seconds=CHALLENGE_TTL_SECONDS):
        return None
    return row


def needs_second_factor(user) -> bool:
    """Staff prove admin changes with a passkey or an emailed code, not a password alone (STAFF_SECOND_FACTOR). Until
    email works and they have no passkey, the password still counts, so nobody is locked out of setting up mail."""
    if not (settings.STAFF_SECOND_FACTOR and user.is_staff):
        return False
    from apps.legal.mail import mail_ready

    return user.passkeys.exists() or mail_ready()


def _reauth_methods(user) -> list[str]:
    strong = needs_second_factor(user)
    return [
        *(["passkey"] if user.passkeys.exists() else []),
        "password" if user.has_usable_password() and not strong else "email_code",
    ]


@api_view(["POST"])
def register_begin(request):
    user = request.user
    if (
        not user.email_verified
    ):  # until the inbox is proven, the account may be a squatter's: no lasting sign-in keys
        return Response({"code": "email_unverified"}, status=status.HTTP_403_FORBIDDEN)
    if not recently_authenticated(
        request
    ):  # a stolen session token alone must not plant an attacker's passkey
        return Response(
            {"code": "reauth_required", "methods": _reauth_methods(user)}, status=status.HTTP_403_FORBIDDEN
        )
    opts = generate_registration_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        rp_name=settings.WEBAUTHN_RP_NAME,
        user_id=str(user.id).encode(),
        user_name=user.email,
        user_display_name=user.profile.display_name or user.email,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id)) for c in user.passkeys.all()
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    return Response({"key": _store(opts.challenge, user), "options": options_to_json(opts)})


@api_view(["POST"])
def register_complete(request):
    row = _pop(request.data.get("key"))
    if not row or row.user_id != request.user.id:
        return Response({"detail": "challenge_expired"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        v = verify_registration_response(
            credential=request.data.get("credential"),
            expected_challenge=bytes(row.challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
        )
    except (
        WebAuthnException,
        ValueError,
        KeyError,
        TypeError,
    ):  # bad/forged credential or malformed client JSON
        return Response({"detail": "passkey_invalid"}, status=status.HTTP_400_BAD_REQUEST)
    PasskeyCredential.objects.create(
        user=request.user,
        credential_id=bytes_to_base64url(v.credential_id),
        public_key=v.credential_public_key,
        sign_count=v.sign_count,
        transports=(request.data.get("credential") or {}).get("response", {}).get("transports", []),
        name=(request.data.get("name") or "Passkey")[:64],
    )
    security_event("passkey_added", user_id=request.user.pk)
    return Response(status=status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])  # anonymous, and each call stores a challenge row
def authenticate_begin(request):
    opts = generate_authentication_options(
        rp_id=settings.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return Response({"key": _store(opts.challenge), "options": options_to_json(opts)})


def _verified_passkey(key, credential):
    """The stored passkey that signed this challenge (with the person present and verified), else None."""
    row = _pop(key)
    credential = credential if isinstance(credential, dict) else {}
    cred = (
        PasskeyCredential.objects.select_related("user")
        .filter(credential_id=credential.get("id", ""))
        .first()
    )
    if not row or not cred or not cred.user.is_active:
        return None
    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=bytes(row.challenge),
            expected_rp_id=settings.WEBAUTHN_RP_ID,
            expected_origin=settings.WEBAUTHN_ORIGIN,
            credential_public_key=bytes(cred.public_key),
            credential_current_sign_count=cred.sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError):
        return None
    cred.sign_count = v.new_sign_count
    cred.last_used_at = timezone.now()
    cred.save(update_fields=["sign_count", "last_used_at"])
    return cred


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
@throttle_classes([AuthThrottle])
def authenticate_complete(request):
    cred = _verified_passkey(request.data.get("key"), request.data.get("credential"))
    if not cred:
        security_event("passkey_failed")
        return Response({"detail": "passkey_invalid"}, status=status.HTTP_401_UNAUTHORIZED)
    security_event("passkey_login", user_id=cred.user_id)
    return token_response({**issue_tokens(cred.user, strong=True), "user": MeSerializer(cred.user).data})


@api_view(["POST"])
@throttle_classes([AuthThrottle])
def reauth(request):
    """Prove it is really you again before a sensitive change (adding a passkey): one of your passkeys
    ({key, credential} from passkey/authenticate/begin), your password, or, for accounts without one, a code we email
    (first call sends it, second call with {code} checks it). Answers with a fresh session (auth_time = now)."""
    from rest_framework_simplejwt.exceptions import TokenError
    from rest_framework_simplejwt.tokens import RefreshToken

    from apps.legal.api import otp_gate

    user = request.user
    strong = True
    if request.data.get("credential"):
        cred = _verified_passkey(request.data.get("key"), request.data.get("credential"))
        if not cred or cred.user_id != user.id:
            return Response({"code": "passkey_invalid"}, status=status.HTTP_403_FORBIDDEN)
    elif user.has_usable_password() and not needs_second_factor(user):
        strong = False
        if login_locked(user.email):  # shares the sign-in lockout: no unlimited password guessing here either
            return Response({"code": "too_many_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if not user.check_password(request.data.get("password") or ""):
            login_failed(user.email)
            return Response({"code": "wrong_password"}, status=status.HTTP_403_FORBIDDEN)
        login_succeeded(user.email)
    elif denied := otp_gate(user, str(request.data.get("code") or ""), purpose="reauth"):
        return denied
    try:
        RefreshToken(refresh_from(request)).blacklist()  # the older, non-recent session is replaced
    except TokenError:
        pass
    security_event("reauth", user_id=user.pk, strong=strong)
    return token_response({**issue_tokens(user, strong=strong), "user": MeSerializer(user).data})


def _pk_out(c: PasskeyCredential) -> dict:
    return {"id": c.id, "name": c.name, "created_at": c.created_at, "last_used_at": c.last_used_at}


@api_view(["GET"])
def passkey_list(request):
    return Response([_pk_out(c) for c in request.user.passkeys.order_by("-created_at")])


@api_view(["PATCH", "DELETE"])
def passkey_detail(request, pk):
    c = request.user.passkeys.filter(pk=pk).first()
    if not c:
        return Response({"detail": "not_found"}, status=status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        if (
            not request.user.has_usable_password()
            and request.user.passkeys.count() == 1
            and not request.user.google_sub
        ):
            return Response({"code": "last_sign_in_method"}, status=status.HTTP_409_CONFLICT)
        c.delete()
        security_event("passkey_removed", user_id=request.user.pk)
        return Response(status=status.HTTP_204_NO_CONTENT)
    c.name = str(request.data.get("name") or c.name).strip()[:64] or c.name
    c.save(update_fields=["name"])
    return Response(_pk_out(c))
