"""Guest link rules shared by the creator API, the public guest pages and claiming progress after sign-up."""

import hashlib
import hmac
import ipaddress
import logging
import secrets

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from rest_framework.throttling import BaseThrottle

from apps.learning.models import (
    Activity,
    ActivityAttempt,
    Curriculum,
    Enrollment,
    Subsection,
    UserSubsectionState,
)
from apps.orgs.csvsafe import csv_safe  # noqa: F401  (the shared CSV guard; guests.api imports it from here)

from .models import GuestAIUsage, GuestLink, GuestVisitor, hash_token

log = logging.getLogger(__name__)
MAGIC_SALT = "aasan-guest-magic"
MAGIC_MAX_AGE = 7 * 24 * 3600
MAGIC_PER_RECIPIENT_DAY = 3
UNSUB_SALT = "aasan-guest-unsub"
# Auto-checked types only: AI-graded activities cost money and need an account.
AI_GRADED = {"open_input", "code", "task", "browser_task", "roleplay", "artifact_check"}
USABLE = ("ok", "full")  # states in which already-started guests may keep going


def limit(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


def ip_bucket(ip: str) -> str:
    """IPv6 clients usually own a whole /64: rate-limit the prefix, not each address."""
    try:
        addr = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        # Never key on attacker-chosen text: every unparsable value shares one bucket.
        return "invalid" if (ip or "").strip() else "unknown"
    if addr.version == 6:
        if addr.ipv4_mapped:
            return str(addr.ipv4_mapped)
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(addr)


def client_ip(request) -> str:
    return ip_bucket(BaseThrottle().get_ident(request) or "")


def ip_hash(request) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(), f"guest-ip:{client_ip(request)}".encode(), hashlib.sha256
    ).hexdigest()


def public_url(link: GuestLink) -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/g/{link.slug}"


# ── Visitors ─────────────────────────────────────────────────────────


def new_visitor(link: GuestLink, request, name: str = "", email: str = "") -> tuple[GuestVisitor | None, str]:
    """Create a visitor if the link still has room → (visitor, raw token) or (None, state)."""
    with transaction.atomic():
        locked = GuestLink.objects.select_for_update().get(
            pk=link.pk
        )  # max_uses must hold under concurrent starts
        st = locked.state()
        if st != "ok":
            return None, st
        raw = secrets.token_urlsafe(32)
        v = GuestVisitor.objects.create(
            link=locked,
            token_hash=hash_token(raw),
            name=name[:80],
            email=email.lower()[:254],
            ip_hash=ip_hash(request),
        )
    return v, raw


def visitor_from(request, link: GuestLink) -> GuestVisitor | None:
    raw = str(request.headers.get("X-Guest-Token") or "")
    if not 20 <= len(raw) <= 100:
        return None
    return GuestVisitor.objects.filter(link=link, token_hash=hash_token(raw)).first()


def rotate_token(visitor: GuestVisitor) -> str:
    raw = secrets.token_urlsafe(32)
    visitor.token_hash = hash_token(raw)
    visitor.save(update_fields=["token_hash", "last_seen"])
    return raw


def magic_token(visitor: GuestVisitor) -> str:
    return signing.dumps({"v": visitor.id, "l": visitor.link_id, "n": visitor.magic_version}, salt=MAGIC_SALT)


def magic_url(visitor: GuestVisitor) -> str:
    return f"{public_url(visitor.link)}?m={magic_token(visitor)}"


def use_magic(link: GuestLink, token: str) -> tuple[GuestVisitor | None, str]:
    """Single use: the payload carries the visitor's magic_version, bumped here → (visitor, new raw token)."""
    try:
        data = signing.loads(token, salt=MAGIC_SALT, max_age=MAGIC_MAX_AGE)
    except signing.BadSignature:
        return None, ""
    if data.get("l") != link.id:
        return None, ""
    with transaction.atomic():
        v = GuestVisitor.objects.select_for_update().filter(pk=data.get("v"), link=link).first()
        if not v or data.get("n") != v.magic_version:
            return None, ""
        v.magic_version += 1
        raw = secrets.token_urlsafe(32)  # the old device's token stops working
        v.token_hash = hash_token(raw)
        v.save(update_fields=["magic_version", "token_hash", "last_seen"])
    return v, raw


def _recipient_ok(email: str) -> bool:
    """At most a few magic-link emails per address per day, whoever asks for them."""
    key = "guest-magic:" + hashlib.sha256(email.lower().encode()).hexdigest()
    cache.add(key, 0, 24 * 3600)
    try:
        n = cache.incr(key)
    except ValueError:
        cache.set(key, 1, 24 * 3600)
        n = 1
    return n <= limit("GUEST_MAGIC_PER_RECIPIENT_DAY", MAGIC_PER_RECIPIENT_DAY)


def send_magic_link(visitor: GuestVisitor) -> str:
    """Fixed text only — nothing a stranger typed (like a name) is echoed into someone's inbox.
    → "" when sent, else an error code ("mail_limit" | "email_not_configured")."""
    from django.core.mail import send_mail

    from apps.legal.mail import EMAIL_NOT_CONFIGURED, mail_ready

    if not mail_ready():
        return EMAIL_NOT_CONFIGURED
    if not visitor.email or not _recipient_ok(visitor.email):
        return "mail_limit"
    body = (
        "Hello,\n\nSomeone (hopefully you) asked to continue a free Aasan lesson with this email address.\n"
        f"Use this link to pick up where you left off. It works once, on any device, for 7 days:\n{magic_url(visitor)}\n\n"
        "If you didn't ask for this, you can ignore this email.\n\n— Aasan"
    )
    try:
        send_mail("Continue your Aasan lesson", body, None, [visitor.email], fail_silently=False)
    except Exception:
        log.warning("guest magic-link mail failed for visitor %s", visitor.id, exc_info=True)
        return "send_failed"
    return ""


# ── Course content for guests ────────────────────────────────────────


def course_lessons(course: Curriculum):
    return Subsection.objects.filter(
        section__curriculum=course, archived=False, section__archived=False
    ).order_by("section__order", "order")


def guest_lesson(link: GuestLink, lesson_id: int) -> Subsection | None:
    if link.target_kind != GuestLink.Target.COURSE or not link.course_id:
        return None
    return course_lessons(link.course).filter(pk=lesson_id).first()


def guest_activity(link: GuestLink, activity_id: int) -> Activity | None:
    if link.target_kind != GuestLink.Target.COURSE or not link.course_id:
        return None
    return Activity.objects.filter(
        pk=activity_id, kind="lesson", subsection__in=course_lessons(link.course)
    ).first()


def lesson_really_done(visitor: GuestVisitor, sub: Subsection) -> bool:
    """Every auto-graded lesson activity was answered by this guest (AI-graded ones are locked for guests)."""
    needed = set(
        sub.activities.filter(kind="lesson").exclude(type__in=AI_GRADED).values_list("id", flat=True)
    )
    done = set(visitor.attempts.filter(activity_id__in=needed).values_list("activity_id", flat=True))
    return bool(needed) and needed <= done


# ── Daily AI allowance for guests ────────────────────────────────────


def _owner_tier(owner) -> str:
    """paid (staff, or on a paid plan) | verified (email confirmed) | new. Free accounts are cheap to make in bulk."""
    from apps.billing.services import current_plan

    if owner.is_staff or current_plan(owner).price_paise > 0:
        return "paid"
    return "verified" if owner.email_verified else "new"


def charge_ai(link: GuestLink, request, units: int = 1) -> bool:
    """Reserve AI units for today; False when any cap is used up: this link, this IP (/64 for IPv6), everything the
    link's owner shares, or all guests on the platform.
    A free owner's links share at most GUEST_AI_FREE_OWNER_SHARE % of the pool between them. Free owners only draw on part of the platform pool (GUEST_AI_FREE_SHARE %), and unverified ones on a smaller part
    (GUEST_AI_NEW_SHARE %), so many throwaway accounts can't use up what paying creators' guests rely on."""
    today = timezone.localdate()
    total = limit("GUEST_AI_GLOBAL_DAY", 5000)
    tier = _owner_tier(link.owner)
    owner_cap = limit("GUEST_AI_PER_OWNER_DAY", 400)
    if tier != "paid":
        # One free owner (verified or not) gets only a small slice, so a handful of verified throwaway accounts can't
        # use up the free pool every other free creator's guests share.
        owner_cap = min(owner_cap, max(1, total * limit("GUEST_AI_FREE_OWNER_SHARE", 2) // 100))
    caps = [
        (f"link:{link.id}", limit("GUEST_AI_PER_LINK_DAY", 200)),
        (f"ip:{ip_hash(request)[:40]}", limit("GUEST_AI_PER_IP_DAY", 30)),
        (f"owner:{link.owner_id}", owner_cap),
    ]
    if tier == "new":
        caps.append(("global:new", total * limit("GUEST_AI_NEW_SHARE", 20) // 100))
    if tier != "paid":
        caps.append(("global:free", total * limit("GUEST_AI_FREE_SHARE", 80) // 100))
    caps.append(("global", total))
    with transaction.atomic():
        rows = []
        for key, cap in caps:
            row, _ = GuestAIUsage.objects.select_for_update().get_or_create(key=key, day=today)
            if row.units + units > cap:
                return False
            rows.append(row.pk)
        GuestAIUsage.objects.filter(pk__in=rows).update(units=F("units") + units)
    return True


# ── Sign-up: move guest progress onto the new account ────────────────


def claim(visitor_id: int, user) -> dict:
    """Copy only what the guest really did: their answers (and finished role-plays). Lessons become 'in progress';
    completing them (and anything that follows from completion, like certificates) uses the normal learner path."""
    out = {"course_id": None, "attempts": 0, "lessons": 0, "roleplays": 0}
    with transaction.atomic():
        visitor = (
            GuestVisitor.objects.select_for_update(of=("self",))
            .select_related("link__course")
            .get(pk=visitor_id)
        )  # one copy only
        if visitor.claimed_by_id and visitor.claimed_by_id != user.id:
            return {"code": "already_claimed"}
        link = visitor.link
        if link.state() not in USABLE:
            return {"code": f"link_{link.state()}"}
        course_ids = set(
            Activity.objects.filter(pk__in=visitor.attempts.values("activity")).values_list(
                "subsection__section__curriculum", flat=True
            )
        )
        if link.course_id:
            course_ids.add(link.course_id)
        for cur in Curriculum.objects.filter(pk__in=course_ids, published_at__isnull=False):
            if cur.owner_id != user.id:
                Enrollment.objects.get_or_create(user=user, curriculum=cur)
        if link.course_id and link.course.published_at:
            out["course_id"] = link.course_id
        if not visitor.claimed_by_id:
            subs = set()
            for a in visitor.attempts.select_related("activity"):
                ActivityAttempt.objects.create(
                    user=user,
                    activity=a.activity,
                    answer=a.answer,
                    score=a.score,
                    correct=a.correct,
                    feedback=a.feedback,
                )
                subs.add(a.activity.subsection_id)
                out["attempts"] += 1
            for sub in Subsection.objects.filter(pk__in=subs, section__curriculum__in=course_ids):
                st, created = UserSubsectionState.objects.get_or_create(
                    user=user,
                    subsection=sub,
                    defaults={
                        "status": UserSubsectionState.Status.IN_PROGRESS,
                        "started_at": visitor.created_at,
                    },
                )
                if not created and st.status == UserSubsectionState.Status.NOT_STARTED:
                    st.status, st.started_at = UserSubsectionState.Status.IN_PROGRESS, visitor.created_at
                    st.save(update_fields=["status", "started_at"])
                out["lessons"] += 1
            out["roleplays"] = _claim_roleplays(visitor, user)
            visitor.claimed_by, visitor.claimed_at = user, timezone.now()
            visitor.save(update_fields=["claimed_by", "claimed_at", "last_seen"])
    return out


def _claim_roleplays(visitor, user) -> int:
    from apps.roleplay.models import RolePlaySession, RolePlayTurn

    n = 0
    for gr in visitor.roleplays.filter(status="completed"):
        s = RolePlaySession.objects.create(
            user=user,
            scenario=gr.scenario,
            status=RolePlaySession.Status.COMPLETED,
            result=gr.result,
            ended_at=timezone.now(),
        )
        RolePlayTurn.objects.bulk_create(
            [RolePlayTurn(session=s, role=t["role"], text=t["text"]) for t in gr.turns]
        )
        n += 1
    return n
