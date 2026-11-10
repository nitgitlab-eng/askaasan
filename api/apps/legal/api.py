"""Public site/legal info, terms consent, personal-data export and account deletion (DPDP Act 2023 rights)."""

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers as dj_serializers
from django.core.mail import send_mail
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.staff import AdminSection

from .models import TERMS_VERSION, SiteInfo

SITE_FIELDS = [
    "brand",
    "legal_name",
    "address",
    "city",
    "support_email",
    "phone",
    "grievance_officer",
    "grievance_email",
    "gstin",
    "refund_days",
    "state",
    "hsn_sac",
]


def site() -> SiteInfo:
    return SiteInfo.objects.filter(pk=1).first() or SiteInfo(pk=1)


def site_out() -> dict:
    s = site()
    return {**{f: getattr(s, f) for f in SITE_FIELDS}, "terms_version": TERMS_VERSION}


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def site_info(request):
    return Response(site_out())


class SitePatch(serializers.ModelSerializer):
    class Meta:
        model = SiteInfo
        fields = SITE_FIELDS
        extra_kwargs = {"refund_days": {"min_value": 0, "max_value": 30}}


@api_view(["GET", "PATCH"])
@permission_classes([AdminSection])
def admin_site(request):
    if request.method == "PATCH":
        row, _ = SiteInfo.objects.get_or_create(pk=1)
        ser = SitePatch(row, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
    return Response(site_out())


# ── Consent ──────────────────────────────────────────────────────────


class ConsentIn(serializers.Serializer):
    accept = serializers.BooleanField()
    age_band = serializers.ChoiceField(choices=["adult", "minor"])
    guardian_email = serializers.EmailField(required=False, allow_blank=True)

    def validate(self, d):
        if not d["accept"]:
            raise serializers.ValidationError({"accept": "must_accept"})
        if d["age_band"] == "minor" and not d.get("guardian_email"):
            raise serializers.ValidationError({"guardian_email": "guardian_required"})
        return d


GUARDIAN_MAILS_PER_DAY = 3


def _new_guardian(user, age_band: str, guardian_email: str) -> bool:
    return bool(
        age_band == "minor"
        and guardian_email
        and guardian_email.lower() != (user.guardian_email or "").lower()
    )


def record_consent(user, age_band: str, guardian_email: str = "") -> None:
    from apps.accounts.views import mail_allowed

    first_guardian = _new_guardian(user, age_band, guardian_email)
    new_email = guardian_email.lower() if age_band == "minor" else ""
    fields = ["terms_version", "terms_accepted_at", "age_band", "guardian_email"]
    if new_email != (user.guardian_email or "").lower():
        user.guardian_nonce = (
            ""  # the previous guardian's view link stops working; a new one is minted lazily
        )
        # A different guardian must confirm afresh: consent belongs to the person who gave it.
        user.guardian_consent_at = user.guardian_objected_at = None
        fields += ["guardian_nonce", "guardian_consent_at", "guardian_objected_at"]
    user.terms_version, user.terms_accepted_at = TERMS_VERSION, timezone.now()
    user.age_band, user.guardian_email = age_band, new_email
    user.save(update_fields=fields)
    # Per-recipient cap lives here so every caller (consent page AND sign-up) is covered: nobody can flood one inbox.
    if first_guardian and mail_allowed(f"guardian-mail:{user.guardian_email}", GUARDIAN_MAILS_PER_DAY):
        from apps.accounts.guardian import send_consent_request

        send_consent_request(user)


@api_view(["POST"])
def consent(request):
    from apps.accounts.views import mail_allowed

    ser = ConsentIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if request.user.age_band == "minor" and ser.validated_data["age_band"] == "adult":
        # Otherwise an under-18 could skip their guardian's consent by ticking "adult"; support changes it (on 18).
        return Response({"code": "age_change_needs_support"}, status=status.HTTP_409_CONFLICT)
    g = ser.validated_data.get("guardian_email", "")
    # A new guardian address gets an email; cap that per account here (record_consent caps it per recipient).
    if _new_guardian(request.user, ser.validated_data["age_band"], g) and not mail_allowed(
        f"guardian-mail:u{request.user.id}", GUARDIAN_MAILS_PER_DAY
    ):
        return Response({"code": "too_many_emails"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    record_consent(request.user, ser.validated_data["age_band"], ser.validated_data.get("guardian_email", ""))
    return Response({"ok": True, "version": TERMS_VERSION})


# ── Export ───────────────────────────────────────────────────────────

# Security material is not "your data" and must never land in a downloaded file.
SKIP_MODELS = {
    "token_blacklist.OutstandingToken",
    "token_blacklist.BlacklistedToken",
    "accounts.OneTimeToken",
    "extension.ExtensionPairing",  # its `code` is a live pairing secret
}
SKIP_FIELDS = {
    "password",
    "respondent_key",
    "token_hash",
    "encrypted_key",
    "public_key",
    "credential_id",
    "sign_count",
    "encrypted_refresh_token",
    "code_hash",
    "code_challenge",
    "guardian_nonce",
    "token_enc",  # a learner's own MCP server token (workshops)
}


def _rows(model, **filters):
    data = json.loads(dj_serializers.serialize("json", model.objects.filter(**filters)))
    return [{"id": r["pk"], **{k: v for k, v in r["fields"].items() if k not in SKIP_FIELDS}} for r in data]


def collect(user) -> dict:
    from django.apps import apps

    out: dict = {"exported_at": timezone.now().isoformat(), "terms_version_accepted": user.terms_version}
    # Every model that points straight at the user.
    for model in apps.get_models():
        if f"{model._meta.app_label}.{model.__name__}" in SKIP_MODELS:
            continue
        for f in model._meta.fields:
            if f.is_relation and f.related_model is get_user_model() and f.name in ("user", "owner"):
                rows = _rows(model, **{f.name: user})
                if rows:
                    out[f"{model._meta.app_label}.{model.__name__}"] = rows
    out["accounts.User"] = _rows(get_user_model(), pk=user.pk)
    # One level down: the content of the user's own conversations and role-plays.
    from apps.mentor.models import Message
    from apps.roleplay.models import RolePlayTurn

    out["mentor.Message"] = _rows(Message, conversation__user=user)
    out["roleplay.RolePlayTurn"] = _rows(RolePlayTurn, session__user=user)
    from apps.workshops.models import WorkshopAgentServer, WorkshopEvent, WorkshopTurn

    out["workshops.WorkshopTurn"] = _rows(WorkshopTurn, session__user=user)
    out["workshops.WorkshopEvent"] = _rows(WorkshopEvent, session__user=user)
    out["workshops.WorkshopAgentServer"] = _rows(WorkshopAgentServer, session__user=user)  # never the token
    return out


@api_view(["GET"])
def export(request):
    body = json.dumps(collect(request.user), ensure_ascii=False, indent=1, default=str)
    resp = HttpResponse(body, content_type="application/json; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="aasan-my-data-{timezone.localdate()}.json"'
    return resp


# ── Delete ───────────────────────────────────────────────────────────

ARCHIVE_EMAIL = "archive@aasan.invalid"
DELETE_PW_MAX_FAILS = 5


def _archive_user():
    User = get_user_model()
    u, created = User.objects.get_or_create(email=ARCHIVE_EMAIL, defaults={"is_active": False})
    if created:
        u.set_unusable_password()
        u.save()
        u.profile.display_name = "Aasan"
        u.profile.save()
    elif u.is_active or u.has_usable_password():  # never hand courses to a row someone can sign in to
        from apps.accounts.tokens import revoke_all_sessions

        u.is_active = False
        u.set_unusable_password()
        u.save(update_fields=["is_active", "password"])
        revoke_all_sessions(u, "archive")
    return u


def blockers(user) -> list[dict]:
    """Orgs where this user is the only owner but others still belong — they must hand over first."""
    from apps.orgs.models import Membership

    out = []
    for m in Membership.objects.filter(user=user, role="owner").select_related("org"):
        others = Membership.objects.filter(org=m.org).exclude(user=user)
        if others.exists() and not others.filter(role="owner").exists():
            out.append({"slug": m.org.slug, "name": m.org.name})
    return out


OTP_MAILS_PER_DAY = 5
OTP_MAIL = {
    "delete": (
        "Your Aasan account deletion code",
        "If you didn't ask to delete your account, ignore this email and sign out of other devices.",
    ),
    "reauth": (
        "Your Aasan security code",
        (
            "Someone signed in as you is adding a new sign-in method (passkey). "
            "If this wasn't you, don't share the code and change your password."
        ),
    ),
}


def otp_gate(user, code: str, purpose: str = "delete"):
    """Email a 6-digit code on the first call; accept it (once, 15 min, 5 tries) on the second."""
    import hashlib
    import secrets

    from apps.accounts import counters
    from apps.accounts.views import mail_allowed

    key = f"{purpose}-otp:{user.id}"
    tries_key = f"{key}:tries"
    held = counters.store().get(key)
    if code and held:
        if counters.bump(tries_key, 15 * 60) > 5:  # atomic: parallel guesses can't share one try
            counters.clear(key)
            counters.clear(tries_key)
            return Response({"code": "otp_locked"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if secrets.compare_digest(held["h"], hashlib.sha256(code.strip().encode()).hexdigest()):
            counters.clear(key)
            counters.clear(tries_key)
            return None
        return Response({"code": "wrong_code"}, status=status.HTTP_403_FORBIDDEN)
    from .mail import EMAIL_NOT_CONFIGURED, mail_ready

    if not mail_ready():  # the code could never arrive — say why instead of "we emailed you a code"
        return Response({"code": EMAIL_NOT_CONFIGURED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not mail_allowed(
        f"{purpose}-otp-mail:u{user.id}", OTP_MAILS_PER_DAY
    ):  # no unlimited mail to the inbox
        return Response({"code": "too_many_emails"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    otp = f"{secrets.randbelow(10**6):06d}"
    subject, note = OTP_MAIL[purpose]
    try:
        send_mail(
            subject,
            f"Your code is {otp}. It expires in 15 minutes.\n{note}",
            None,
            [user.email],
        )
    except Exception:  # noqa: BLE001 — SMTP down/misconfigured
        return Response({"code": "send_failed"}, status=status.HTTP_502_BAD_GATEWAY)
    counters.store().set(key, {"h": hashlib.sha256(otp.encode()).hexdigest()}, 15 * 60)
    counters.clear(tries_key)
    return Response({"code": "otp_sent"}, status=status.HTTP_202_ACCEPTED)


@api_view(["POST"])
def delete_account(request):
    user = request.user
    if (request.data.get("confirm") or "").strip().upper() != "DELETE":
        return Response({"code": "confirm_required"}, status=status.HTTP_400_BAD_REQUEST)
    if user.has_usable_password():
        from apps.accounts import counters

        key = f"delete-pw-fail:{user.id}"
        if (
            counters.count(key) >= DELETE_PW_MAX_FAILS
        ):  # same idea as the login lockout: no unlimited guessing
            return Response({"code": "too_many_attempts"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        if not user.check_password(request.data.get("password") or ""):
            counters.bump(key, 15 * 60)
            return Response({"code": "wrong_password"}, status=status.HTTP_403_FORBIDDEN)
        counters.clear(key)
    elif denied := otp_gate(user, str(request.data.get("code") or "")):
        return denied  # Google / passkey accounts: a stolen session token alone can't delete the account
    if user.is_superuser:
        return Response({"code": "superuser"}, status=status.HTTP_409_CONFLICT)
    if b := blockers(user):
        return Response({"code": "sole_owner", "orgs": b}, status=status.HTTP_409_CONFLICT)

    from apps.billing.models import Order
    from apps.learning.models import Curriculum, Enrollment
    from apps.orgs.models import Assignment, Organization
    from apps.studio.models import LectureVideo
    from apps.support.models import ProblemReport

    email = user.email
    with transaction.atomic():
        # Courses other people learn from stay available, without the author's identity.
        ids = set(
            Enrollment.objects.filter(curriculum__owner=user)
            .exclude(user=user)
            .values_list("curriculum_id", flat=True)
        )
        ids |= set(Assignment.objects.filter(curriculum__owner=user).values_list("curriculum_id", flat=True))
        if ids:
            archive = _archive_user()
            Curriculum.objects.filter(id__in=ids).update(owner=archive)
            # Their lecture videos are part of those courses; owner CASCADE would otherwise drop them with the user.
            LectureVideo.objects.filter(subsection__section__curriculum_id__in=ids).update(owner=archive)
        # Problem reports hold their email, words and screenshots: personal data, so they go too.
        ProblemReport.objects.filter(user=user).delete()
        # Payment records are kept for tax law (GST), detached from the person.
        Order.objects.filter(user=user).update(user=None)
        # Orgs where they were the only member go with them.
        for org in Organization.objects.filter(memberships__user=user, memberships__role="owner"):
            if not org.memberships.exclude(user=user).exists():
                org.delete()
        user.delete()
    send_mail(
        "Your Aasan account has been deleted",
        "Your account and personal data have been deleted. Payment records "
        "are kept without your name as required by tax law. Thank you for learning with us.",
        None,
        [email],
        fail_silently=True,
    )
    return Response({"ok": True})


# ── Admin: outgoing email (SMTP) ─────────────────────────────────────


class MailPatch(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    host = serializers.CharField(max_length=200, required=False, allow_blank=True)
    port = serializers.IntegerField(min_value=1, max_value=65535, required=False)
    security = serializers.ChoiceField(choices=["tls", "ssl", "none"], required=False)
    username = serializers.CharField(max_length=200, required=False, allow_blank=True)
    password = serializers.CharField(max_length=300, required=False, allow_blank=True, trim_whitespace=False)
    from_email = serializers.EmailField(required=False, allow_blank=True)
    from_name = serializers.CharField(max_length=80, required=False)


def _mail_out():
    from .models import MailConfig

    c = MailConfig.objects.filter(pk=1).first() or MailConfig(pk=1)
    pw = c.password() if c.encrypted_password else ""
    return {
        "enabled": c.enabled,
        "host": c.host,
        "port": c.port,
        "security": c.security,
        "username": c.username,
        "password": "••••" if pw else None,  # never any part of an SMTP password (it is often short)
        "from_email": c.from_email,
        "from_name": c.from_name,
        "ready": c.ready,
        "fallback": settings.EMAIL_FALLBACK_BACKEND.rsplit(".", 2)[-2],
    }


@api_view(["GET", "PATCH"])
@permission_classes([AdminSection])
def admin_mail(request):
    from apps.providers import crypto

    from .models import MailConfig

    if request.method == "PATCH":
        ser = MailPatch(data=request.data)
        ser.is_valid(raise_exception=True)
        d = dict(ser.validated_data)
        row, _ = MailConfig.objects.get_or_create(pk=1)
        if "password" in d:
            pw = d.pop("password")
            row.encrypted_password = crypto.encrypt(pw) if pw else ""
        elif any(k in d and d[k] != getattr(row, k) for k in ("host", "port", "security", "username")):
            row.encrypted_password = (
                ""  # a password belongs to one server and login; never send it somewhere new
            )
        for k, v in d.items():
            setattr(row, k, v)
        row.save()
    return Response(_mail_out())


@api_view(["POST"])
@permission_classes([AdminSection])
def admin_mail_test(request):
    """Send a real test email synchronously and report the exact SMTP error if it fails."""
    from django.core.mail import EmailMessage

    from .mail import _smtp_connection
    from .models import MailConfig

    cfg = MailConfig.objects.filter(pk=1).first()
    to = (request.data.get("to") or request.user.email).strip()
    if not cfg or not cfg.ready:
        return Response(
            {"ok": False, "detail": "Fill in the SMTP host and From address, then save."}, status=400
        )
    try:
        msg = EmailMessage(
            "Aasan test email ✅",
            "Your SMTP settings work. Learners will now receive Aasan emails.",
            f"{cfg.from_name} <{cfg.from_email}>",
            [to],
        )
        _smtp_connection(cfg).send_messages([msg])
    except Exception as e:  # noqa: BLE001 — show the admin the real reason (auth, TLS, DNS…)
        return Response({"ok": False, "detail": f"{type(e).__name__}: {str(e)[:300]}"}, status=400)
    return Response({"ok": True, "detail": f"Sent to {to}. Check the inbox (and spam folder)."})


# ── Sub-processors (for the DPA), generated from what is actually configured ──

PURPOSE = {
    "tutor": "AI mentor, course & lesson writing",
    "utility": "Grading, insights and summaries",
    "vision": "Live Class and screenshot grading",
    "image": "Lesson illustrations",
    "embedding": "Search in uploaded notes",
    "stt": "Speech-to-text",
    "tts": "Text-to-speech",
    "tts_ta": "Text-to-speech (Tamil)",
}
VENDOR = {
    "anthropic": ("Anthropic PBC", "USA"),
    "openai": ("OpenAI, L.L.C.", "USA"),
    "gemini": ("Google LLC (Gemini API)", "USA"),
    "google": ("Google LLC (Cloud Speech)", "USA / India"),
    "sarvam": ("Sarvam AI", "India"),
    "deepgram": ("Deepgram, Inc.", "USA"),
}


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def subprocessors(request):
    from apps.billing.services import pay_config
    from apps.providers.catalog import CAPABILITIES
    from apps.providers.services import resolve

    rows: dict[str, dict] = {}
    for cap in CAPABILITIES:
        cfg = resolve(cap)
        if not cfg.enabled or cfg.provider in ("browser", "fake") or cfg.provider not in VENDOR:
            continue
        name, where = VENDOR[cfg.provider]
        rows.setdefault(name, {"name": name, "location": where, "purposes": []})["purposes"].append(
            PURPOSE.get(cap, cap)
        )
    if "livekit.cloud" in (
        settings.LIVEKIT_URL or ""
    ):  # self-hosted LiveKit runs on our own servers: not a vendor
        rows["LiveKit"] = {
            "name": "LiveKit, Inc. (LiveKit Cloud)",
            "location": "USA / global",
            "purposes": ["Carrying live voice calls (audio is relayed, not recorded)"],
        }
    if pay_config().key_id:
        rows["Razorpay"] = {
            "name": "Razorpay Software Pvt Ltd",
            "location": "India",
            "purposes": ["Payments"],
        }
    from .models import MailConfig

    mc = MailConfig.objects.filter(pk=1).first()
    if mc and mc.ready:
        vendor = next(
            (
                v
                for k, v in (
                    ("gmail", "Google"),
                    ("google", "Google"),
                    ("zoho", "Zoho"),
                    ("sendgrid", "SendGrid"),
                    ("amazonaws", "Amazon SES"),
                    ("mailgun", "Mailgun"),
                    ("postmarkapp", "Postmark"),
                    ("brevo", "Brevo"),
                    ("sendinblue", "Brevo"),
                    ("office365", "Microsoft"),
                    ("outlook", "Microsoft"),
                )
                if k in (mc.host or "").lower()
            ),
            "",
        )
        rows["email"] = {
            "name": f"Email delivery ({vendor})" if vendor else "Email delivery provider",
            "location": "—",
            "purposes": ["Sending account and reminder emails"],
        }
    from .models import DPA_VERSION

    return Response({"version": DPA_VERSION, "subprocessors": list(rows.values())})
