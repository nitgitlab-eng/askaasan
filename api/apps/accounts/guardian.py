"""B3 guardian view (DPDP: under-18 learners). The guardian who consented gets a private, read-only progress link and
a weekly email. Only progress numbers and lesson titles are shared — never chats, answers, documents or photos."""

import secrets
from datetime import timedelta

from django.conf import settings
from django.core import signing
from django.utils import timezone
from rest_framework import permissions, serializers, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

SALT = "aasan-guardian-view"


class GuardianThrottle(AnonRateThrottle):
    rate = "60/hour"


def _nonce(user) -> str:
    if not user.guardian_nonce:
        user.guardian_nonce = secrets.token_hex(8)
        user.save(update_fields=["guardian_nonce"])
    return user.guardian_nonce


def guardian_link(user) -> str:
    token = signing.dumps({"u": user.id, "n": _nonce(user)}, salt=SALT, compress=True)
    return f"{settings.FRONTEND_URL}/guardian/{token}"


def _user_from(token):
    from .models import User

    try:
        data = signing.loads(token, salt=SALT)
    except signing.BadSignature:
        return None
    u = (
        User.objects.filter(pk=data.get("u"), is_active=True, age_band="minor")
        .select_related("profile")
        .first()
    )
    return u if u and u.guardian_nonce and u.guardian_nonce == data.get("n") else None


def consent_pending(user) -> bool:
    """An under-18 whose guardian hasn't confirmed consent yet (or objected): AI features stay locked."""
    return getattr(user, "age_band", "") == "minor" and not getattr(user, "guardian_consent_at", None)


def consent_state(user) -> str | None:
    if getattr(user, "age_band", "") != "minor":
        return None
    if user.guardian_consent_at:
        return "given"
    return "objected" if user.guardian_objected_at else "pending"


def send_consent_request(user) -> bool:
    """Ask the guardian to confirm or refuse, by link. A failed send is logged (the learner can resend)."""
    import logging

    from django.core.mail import send_mail

    from apps.legal.api import site

    s = site()
    contact = s.grievance_email or s.support_email or "our support team"
    body = (
        f"Hello,\n\n{user.email} told us you are their parent or guardian and asked to use {s.brand}, an AI "
        "learning mentor.\n\nWhat we collect: their name, learning progress, chats with the AI mentor, voice they "
        "speak to it and anything they upload. AI providers process these to answer them. We never show ads or sell "
        "data.\n\nThe AI mentor, voice, role-play, workshops and uploads stay switched off until you choose:\n\n"
        f"  {guardian_link(user)}\n\n"
        "Open the link and choose 'I agree' or 'I do not agree'. The same link shows their progress later.\n\n"
        f"Questions, or want their data deleted? Write to {contact}."
    )
    try:
        send_mail(f"Please confirm: your child wants to use {s.brand}", body, None, [user.guardian_email])
    except Exception:  # noqa: BLE001 — SMTP down; the learner sees "pending" and can resend
        logging.getLogger(__name__).warning("guardian consent email failed for user %s", user.id)
        return False
    return True


def summary(user, days: int = 7) -> dict:
    from apps.game.services import stats_for
    from apps.learning.models import UserSubsectionState
    from apps.study.progress import minutes_by_day

    since = timezone.now() - timedelta(days=days)
    mins = minutes_by_day(user, since)
    done = (
        UserSubsectionState.objects.filter(user=user, status="completed", completed_at__gte=since)
        .select_related("subsection__section__curriculum")
        .order_by("-completed_at")
    )
    s = stats_for(user)
    return {
        "name": (user.profile.display_name or "").split(" ")[0] or "Your child",
        "days": days,
        "minutes": sum(mins.values()),
        "active_days": len([d for d, m in mins.items() if m]),
        "lessons": [
            {
                "title": st.subsection.title,
                "course": st.subsection.section.curriculum.title,
                "score": None if st.score is None else round(st.score * 100),
                "on": timezone.localdate(st.completed_at),
            }
            for st in done[:15]
        ],
        "lessons_count": done.count(),
        "streak": s.streak,
        "last_active": s.last_active,
    }


@api_view(["GET"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([GuardianThrottle])
def guardian_view(request, token):
    u = _user_from(token)
    if not u:
        return Response({"code": "invalid_link"}, status=status.HTTP_404_NOT_FOUND)
    days = 30 if request.query_params.get("days") == "30" else 7
    return Response({**summary(u, days), "digest": u.guardian_digest, "consent": consent_state(u)})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([GuardianThrottle])
def guardian_consent(request, token):
    """The guardian's choice from the emailed link: {"agree": true} unlocks AI features, false keeps them locked."""
    from .security_log import security_event

    u = _user_from(token)
    if not u:
        return Response({"code": "invalid_link"}, status=status.HTTP_404_NOT_FOUND)
    agree = serializers.BooleanField().to_internal_value(request.data.get("agree"))
    now = timezone.now()
    u.guardian_consent_at, u.guardian_objected_at = (now, None) if agree else (None, now)
    u.save(update_fields=["guardian_consent_at", "guardian_objected_at"])
    security_event("guardian_consent" if agree else "guardian_objected", user_id=u.id)
    return Response({"consent": consent_state(u)})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([GuardianThrottle])
def guardian_stop(request, token):
    """One click from the email: stop the weekly email (the link itself keeps working until the learner revokes it)."""
    u = _user_from(token)
    if not u:
        return Response({"code": "invalid_link"}, status=status.HTTP_404_NOT_FOUND)
    u.guardian_digest = False
    u.save(update_fields=["guardian_digest"])
    return Response({"ok": True})


def _n(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _send(user) -> bool:
    from django.core.mail import send_mail

    s = summary(user, 7)
    link = guardian_link(user)
    lessons = (
        "\n".join(f"  • {x['title']} ({x['course']})" for x in s["lessons"][:8])
        or "  (no lessons finished this week)"
    )
    body = (
        f"Hello,\n\nHere is {s['name']}'s week on Aasan:\n"
        f"  Time learning: about {_n(s['minutes'], 'minute')} on {_n(s['active_days'], 'day')}\n"
        f"  Lessons finished: {s['lessons_count']}\n  Current streak: {_n(s['streak'], 'day')}\n\n{lessons}\n\n"
        f"See more (read-only, no login needed): {link}\n\n"
        "You receive this because you agreed to this learner using Aasan as their parent or guardian. "
        f"To stop these weekly emails, open the link above and choose 'Stop weekly emails'."
    )
    try:
        # Fixed subject: the learner types their own display name, so it never goes in a header the guardian trusts.
        send_mail("Weekly learning update from Aasan", body, None, [user.guardian_email], fail_silently=False)
    except Exception:  # noqa: BLE001 — one bad address must not stop the batch
        return False
    return True


def send_weekly(now=None) -> int:
    """Celery beat (daily): each guardian gets one digest per week, on the first run on or after Sunday (so a missed
    Sunday run is caught up on Monday instead of skipping the week)."""
    from .models import User

    today = timezone.localdate(now)
    week_start = today - timedelta(days=(today.weekday() + 1) % 7)  # this week's Sunday
    sent = 0
    for u in (
        User.objects.filter(is_active=True, age_band="minor", guardian_digest=True)
        .exclude(guardian_email="")
        .select_related("profile")
    ):
        if u.guardian_last_sent and u.guardian_last_sent >= week_start:
            continue
        if (
            timezone.localdate(u.date_joined) > week_start
        ):  # joined mid-week: their first digest comes next Sunday
            continue
        # Claim the week first (atomic), so overlapping runs can't both send; give it back if the send fails.
        before = u.guardian_last_sent
        claimed = (
            User.objects.filter(pk=u.pk, guardian_last_sent=before)
            if before
            else User.objects.filter(pk=u.pk, guardian_last_sent__isnull=True)
        ).update(guardian_last_sent=today)
        if not claimed:
            continue
        if _send(u):
            sent += 1
        else:
            User.objects.filter(pk=u.pk, guardian_last_sent=today).update(guardian_last_sent=before)
    return sent


@api_view(["GET", "PATCH", "POST"])
def my_guardian(request):
    """The learner's own controls: see who gets updates, email the link now, turn the weekly email on/off, revoke the link."""
    u = request.user
    if u.age_band != "minor" or not u.guardian_email:
        return Response({"applies": False})
    if request.method == "PATCH" and "digest" in request.data:
        u.guardian_digest = serializers.BooleanField().to_internal_value(
            request.data["digest"]
        )  # "false" is False
        u.save(update_fields=["guardian_digest"])
    if request.method == "POST":
        action = request.data.get("action")
        if action == "revoke":
            u.guardian_nonce = secrets.token_hex(8)  # old links stop working
            u.save(update_fields=["guardian_nonce"])
        elif action == "send":
            from django.core.cache import cache

            from apps.legal.mail import EMAIL_NOT_CONFIGURED, mail_ready

            if not mail_ready():
                return Response({"code": EMAIL_NOT_CONFIGURED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            key = f"guardian-send:{u.id}"
            if cache.get(key):
                return Response({"code": "sent_recently"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            cache.set(key, 1, 3600)
            if not _send(u):
                cache.delete(key)
                return Response({"code": "send_failed"}, status=status.HTTP_502_BAD_GATEWAY)
        elif action == "consent":  # ask the guardian again (lost or failed email)
            from apps.legal.mail import EMAIL_NOT_CONFIGURED, mail_ready

            from .views import mail_allowed

            if not consent_pending(u):
                return Response({"code": "not_pending"}, status=status.HTTP_409_CONFLICT)
            if not mail_ready():
                return Response({"code": EMAIL_NOT_CONFIGURED}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            if not mail_allowed(f"guardian-consent:u{u.id}", 3):
                return Response({"code": "too_many_emails"}, status=status.HTTP_429_TOO_MANY_REQUESTS)
            if not send_consent_request(u):
                return Response({"code": "send_failed"}, status=status.HTTP_502_BAD_GATEWAY)
    return Response(
        {
            "applies": True,
            "email": u.guardian_email,
            "digest": u.guardian_digest,
            "last_sent": u.guardian_last_sent,
            "consent": consent_state(u),
        }
    )
