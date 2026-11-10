"""Super-admin platform dashboard: users, learning activity, revenue and AI spend."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.staff import AdminSection

from .catalog import CAPABILITIES
from .models import LLMUsage, ModelPrice, UsageCounter

ARCHIVE = "archive@aasan.invalid"


def _days(n):
    today = timezone.localdate()
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _series(qs, field, days, agg=None):
    """{date: value} over the window, zero-filled."""
    rows = qs.annotate(d=TruncDate(field)).values("d").annotate(v=agg or Count("id"))
    got = {r["d"]: r["v"] or 0 for r in rows}
    return [{"day": d, "value": got.get(d, 0)} for d in days]


def _price_map():
    return {(p.provider, p.model): p for p in ModelPrice.objects.all()}


def _cost(prices, provider, model, tin, tout):
    p = prices.get((provider, model))
    if not p:
        return None
    return (Decimal(tin) * p.input_per_m + Decimal(tout) * p.output_per_m) / Decimal(1_000_000)


def _feedback(since) -> dict:
    from apps.learning.models import LessonFeedback
    from apps.mentor.models import AnswerFeedback

    fb = AnswerFeedback.objects.filter(updated_at__gte=since)
    by_kind = list(
        fb.values("kind")
        .annotate(up=Count("id", filter=Q(rating=1)), down=Count("id", filter=Q(rating=-1)))
        .order_by("kind")
    )
    worst = list(
        fb.filter(rating=-1)
        .order_by("-updated_at")
        .values("kind", "reason", "comment", "excerpt", "model", "updated_at")[:15]
    )
    lessons = LessonFeedback.objects.filter(updated_at__gte=since)
    low = list(
        lessons.values("subsection__title", "subsection__section__curriculum__title")
        .annotate(n=Count("id"), avg=Avg("rating"))
        .filter(n__gte=1)
        .order_by("avg")[:8]
    )
    return {
        "up": fb.filter(rating=1).count(),
        "down": fb.filter(rating=-1).count(),
        "by_kind": by_kind,
        "worst": worst,
        "lesson_ratings": lessons.count(),
        "lesson_avg": round(lessons.aggregate(a=Avg("rating"))["a"] or 0, 2),
        "lowest_lessons": [
            {
                "lesson": r["subsection__title"],
                "course": r["subsection__section__curriculum__title"],
                "n": r["n"],
                "avg": round(r["avg"], 2),
            }
            for r in low
        ],
    }


@api_view(["GET"])
@permission_classes([AdminSection])
def overview(request):
    from apps.billing.models import Entitlement, Order
    from apps.game.models import XPEvent
    from apps.learning.models import Curriculum, UserSubsectionState
    from apps.live.models import LiveSession
    from apps.media.models import MediaAsset
    from apps.mentor.models import Message
    from apps.orgs.models import Organization
    from apps.roleplay.models import RolePlaySession

    try:
        n = min(90, max(7, int(request.query_params.get("days", 30))))
    except (TypeError, ValueError):
        n = 30
    days = _days(n)
    since = timezone.now() - timedelta(days=n)
    User = get_user_model()
    users = User.objects.exclude(email=ARCHIVE)

    # Learning
    active = XPEvent.objects.filter(day__gte=days[0]).values("day").annotate(v=Count("user", distinct=True))
    active_map = {r["day"]: r["v"] for r in active}

    # Money (paid orders only; test and live kept apart)
    paid = Order.objects.filter(status="paid")
    revenue = {
        m: paid.filter(mode=m).aggregate(
            all=Sum("amount_paise"), window=Sum("amount_paise", filter=Q(paid_at__gte=since))
        )
        for m in ("live", "test")
    }

    # AI
    usage = LLMUsage.objects.filter(created_at__gte=since)
    prices = _price_map()
    by_model = []
    total_cost, priced_all = Decimal(0), True
    for r in (
        usage.values("provider", "model")
        .annotate(calls=Count("id"), tin=Sum("input_tokens"), tout=Sum("output_tokens"))
        .order_by("-tout")
    ):
        c = _cost(prices, r["provider"], r["model"], r["tin"] or 0, r["tout"] or 0)
        priced_all &= c is not None
        total_cost += c or 0
        by_model.append({**r, "cost_inr": round(float(c), 2) if c is not None else None})
    by_task = list(
        usage.values("task")
        .annotate(calls=Count("id"), tokens=Sum("output_tokens") + Sum("input_tokens"))
        .order_by("-tokens")
    )
    top_users = [
        {"email": r["user__email"], "calls": r["calls"], "tokens": r["tokens"]}
        for r in usage.exclude(user=None)
        .values("user__email")
        .annotate(calls=Count("id"), tokens=Sum("output_tokens") + Sum("input_tokens"))
        .order_by("-tokens")[:10]
    ]
    counters = dict(
        UsageCounter.objects.filter(day__gte=days[0]).values_list("metric").annotate(t=Sum("amount"))
    )

    return Response(
        {
            "days": n,
            "users": {
                "total": users.count(),
                "new": users.filter(date_joined__gte=since).count(),
                "verified": users.filter(email_verified=True).count(),
                "minors": users.filter(age_band="minor").count(),
                "tamil_ui": users.filter(profile__language="ta").count(),
                "creators": users.filter(is_creator=True).count(),
                "series": _series(users.filter(date_joined__gte=since), "date_joined", days),
            },
            "learning": {
                "active_7d": XPEvent.objects.filter(day__gte=timezone.localdate() - timedelta(days=6))
                .values("user")
                .distinct()
                .count(),
                "active_window": XPEvent.objects.filter(day__gte=days[0]).values("user").distinct().count(),
                "active_series": [{"day": d, "value": active_map.get(d, 0)} for d in days],
                "lessons_completed": UserSubsectionState.objects.filter(completed_at__gte=since).count(),
                "lessons_series": _series(
                    UserSubsectionState.objects.filter(completed_at__gte=since), "completed_at", days
                ),
                "courses_created": Curriculum.objects.filter(created_at__gte=since).count(),
                "mentor_messages": Message.objects.filter(role="user", created_at__gte=since).count(),
                "roleplays": RolePlaySession.objects.filter(started_at__gte=since).count(),
                "live_classes": LiveSession.objects.filter(started_at__gte=since).count(),
                "live_minutes": round((counters.get("live_seconds") or 0) / 60),
                "orgs": Organization.objects.count(),
            },
            "money": {
                "live_all": revenue["live"]["all"] or 0,
                "live_window": revenue["live"]["window"] or 0,
                "test_all": revenue["test"]["all"] or 0,
                "test_window": revenue["test"]["window"] or 0,
                "paying_now": Entitlement.objects.filter(
                    starts_at__lte=timezone.now(), ends_at__gt=timezone.now()
                )
                .exclude(source="family")  # a family member's access is the owner's payment
                .values("user")
                .distinct()
                .count(),
                "series": _series(
                    paid.filter(mode="live", paid_at__gte=since), "paid_at", days, Sum("amount_paise")
                ),
            },
            "ai": {
                "calls": usage.count(),
                "input_tokens": usage.aggregate(s=Sum("input_tokens"))["s"] or 0,
                "output_tokens": usage.aggregate(s=Sum("output_tokens"))["s"] or 0,
                "cost_inr": round(float(total_cost), 2),
                "cost_complete": priced_all,
                "series": _series(usage, "created_at", days, Sum("output_tokens")),
                "by_model": by_model,
                "by_task": by_task,
                "top_users": top_users,
                "voice_minutes": round((counters.get("stt_seconds") or 0) / 60),
                "tts_chars": int(counters.get("tts_chars") or 0),
                "vision_snapshots": int(counters.get("vision_frames") or 0),
                "images": MediaAsset.objects.filter(kind="generated", created_at__gte=since).count(),
            },
            "feedback": _feedback(since),
            "platform": _platform(since),
        }
    )


def _platform(since) -> dict:
    """Workshops, certificates, organisations, subscriptions and refunds — the rest of the business at a glance."""
    from apps.billing.models import (
        Entitlement,
        FamilyGroup,
        FamilyMember,
        Order,
        OrgSubscription,
        Refund,
        Subscription,
    )
    from apps.credentials.models import Certificate
    from apps.orgs.models import Membership, Organization
    from apps.workshops.models import WorkshopEnrollment

    now = timezone.now()
    enrol = WorkshopEnrollment.objects.all()
    live_subs = Subscription.objects.filter(mode="live", status="active")
    mrr = sum(
        round(s.amount_paise * 30 / max(1, s.plan.period_days)) for s in live_subs.select_related("plan")
    )
    churned = Subscription.objects.filter(mode="live", ended_at__gte=since).count()
    # Family plans bought pay-once (auto-renew ones are already in the subscription MRR): monthly value of the windows
    # running now.
    family_once = Entitlement.objects.filter(
        plan__family=True,
        source="payment",
        order__mode="live",
        order__subscription__isnull=True,
        starts_at__lte=now,
        ends_at__gt=now,
    ).select_related("order", "plan")
    family_mrr = sum(round(e.order.amount_paise * 30 / max(1, e.plan.period_days)) for e in family_once)
    seat_subs = OrgSubscription.objects.filter(starts_at__lte=now, ends_at__gt=now)
    refunds = Refund.objects.exclude(status=Refund.Status.FAILED)
    return {
        "workshops": {
            "enrolments": enrol.count(),
            "enrolments_window": enrol.filter(registered_at__gte=since).count(),
            "revenue_paise": Order.objects.filter(
                status="paid", mode="live", workshop_run__isnull=False
            ).aggregate(s=Sum("amount_paise"))["s"]
            or 0,
            "refunds_due": enrol.filter(refund_due=True).count(),
        },
        "certificates": {
            "total": Certificate.objects.filter(revoked_at=None).count(),
            "window": Certificate.objects.filter(issued_at__gte=since).count(),
            "by_kind": dict(
                Certificate.objects.filter(revoked_at=None).values_list("kind").annotate(n=Count("id"))
            ),
        },
        "orgs": {
            "by_kind": dict(Organization.objects.values_list("kind").annotate(n=Count("id"))),
            "suspended": Organization.objects.exclude(suspended_at=None).count(),
            "paying": seat_subs.values("org").distinct().count(),
            "seats_paid": seat_subs.aggregate(s=Sum("seats"))["s"] or 0,
            "seats_used": Membership.objects.filter(seat=True, org__in=seat_subs.values("org")).count(),
        },
        "subscriptions": {"active": live_subs.count(), "mrr_paise": mrr, "churned_window": churned},
        "family": {
            "groups": FamilyGroup.objects.filter(members__left_at__isnull=True).distinct().count(),
            "members": FamilyMember.objects.filter(left_at__isnull=True)
            .exclude(group__owner_id=F("user_id"))
            .count(),
            "mrr_paise": family_mrr,
        },
        "refunds": {
            "count_window": refunds.filter(created_at__gte=since).count(),
            "paise_window": refunds.filter(created_at__gte=since).aggregate(s=Sum("amount_paise"))["s"] or 0,
        },
    }


class PriceIn(serializers.Serializer):
    provider = serializers.CharField(max_length=24)
    model = serializers.CharField(max_length=80)
    input_per_m = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)
    output_per_m = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0)


@api_view(["GET", "PUT"])
@permission_classes([AdminSection])
def model_prices(request):
    """Prices for every model we use or offer. PUT replaces one row; 0/0 deletes it."""
    if request.method == "PUT":
        ser = PriceIn(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        if d["input_per_m"] == 0 and d["output_per_m"] == 0:
            ModelPrice.objects.filter(provider=d["provider"], model=d["model"]).delete()
        else:
            ModelPrice.objects.update_or_create(
                provider=d["provider"],
                model=d["model"],
                defaults={"input_per_m": d["input_per_m"], "output_per_m": d["output_per_m"]},
            )
    seen = set(LLMUsage.objects.values_list("provider", "model").distinct())
    for cap in ("tutor", "utility", "vision"):
        for prov, spec in CAPABILITIES[cap]["providers"].items():
            seen |= {(prov, m) for m in spec["models"]}
    prices = _price_map()
    return Response(
        [
            {
                "provider": p,
                "model": m,
                "input_per_m": float(prices[(p, m)].input_per_m) if (p, m) in prices else None,
                "output_per_m": float(prices[(p, m)].output_per_m) if (p, m) in prices else None,
            }
            for p, m in sorted(seen)
            if p != "fake"
        ]
    )


@api_view(["GET"])
@permission_classes([AdminSection])
def system_check(request):
    """Everything an operator must get right before (and after) launch, with where to fix it."""
    import os

    from django.conf import settings

    from apps.billing.services import pay_config
    from apps.legal.models import MailConfig, SiteInfo

    from .services import needs_key, resolve

    items = []

    def add(group, key, label, status, detail, link=""):
        items.append(
            {"group": group, "key": key, "label": label, "status": status, "detail": detail, "link": link}
        )

    forced = settings.LLM_FORCE_PROVIDER
    for cap, label, required in (
        ("tutor", "Mentor & course writing", True),
        ("utility", "Grading & quick tasks", True),
        ("vision", "Vision (Live Class, screenshot grading)", True),
        ("image", "Image generation", False),
        ("embedding", "Embeddings (smarter note search)", False),
        ("stt", "Listening (speech-to-text)", False),
        ("tts", "Speaking (text-to-speech)", False),
        ("tts_ta", "Speaking: Tamil", False),
    ):
        cfg = resolve(cap)
        if forced:
            add(
                "AI",
                cap,
                label,
                "warn",
                f"Demo mode: LLM_FORCE_PROVIDER={forced} — answers are canned.",
                "/admin/providers",
            )
        elif not cfg.enabled:
            add("AI", cap, label, "error" if required else "info", "Switched off.", "/admin/providers")
        elif cfg.provider == "browser":
            add("AI", cap, label, "ok", "Uses the learner's browser (free, no key).", "/admin/providers")
        elif needs_key(cfg.provider, cap) and not cfg.key:
            add(
                "AI",
                cap,
                label,
                "error" if required else "info",
                f"{cfg.provider} selected but no API key saved." + ("" if required else " Optional."),
                "/admin/providers",
            )
        else:
            add(
                "AI",
                cap,
                label,
                "ok",
                f"{cfg.provider} · {cfg.model} (key from {'admin' if cfg.source == 'db' else '.env'}). Use Test to confirm.",
                "/admin/providers",
            )

    pc = pay_config()
    if not (pc.key_id and pc.secret):
        add(
            "Payments",
            "razorpay",
            "Razorpay",
            "warn",
            "No keys yet — Upgrade buttons are disabled.",
            "/admin/payments",
        )
    else:
        add(
            "Payments",
            "razorpay",
            "Razorpay",
            "ok" if pc.ready else "warn",
            f"{(pc.mode or '').upper()} mode, checkout {'on' if pc.ready else 'off'}.",
            "/admin/payments",
        )
        add(
            "Payments",
            "webhook",
            "Razorpay webhook secret",
            "ok" if pc.webhook_secret else "warn",
            "Set."
            if pc.webhook_secret
            else "Not set — payments still work, but a closed tab relies on the learner returning.",
            "/admin/payments",
        )

    mc = MailConfig.objects.filter(pk=1).first()
    add(
        "Email",
        "smtp",
        "Outgoing email (SMTP)",
        "ok" if mc and mc.ready else "warn",
        f"{mc.host}:{mc.port} as {mc.from_email}. Use 'Send test email' to confirm."
        if mc and mc.ready
        else f"Not set — emails go to {settings.EMAIL_FALLBACK_BACKEND.rsplit('.', 2)[-2]} (learners receive nothing).",
        "/admin/email",
    )

    site = SiteInfo.objects.filter(pk=1).first()
    missing = [
        f
        for f in ("legal_name", "address", "support_email", "grievance_officer", "grievance_email")
        if not getattr(site, f, "")
    ]
    add(
        "Legal",
        "site",
        "Business & Grievance Officer details",
        "ok" if not missing else "warn",
        "Complete."
        if not missing
        else f"Missing: {', '.join(missing)} (needed for Razorpay activation and the DPDP Act).",
        "/admin/site",
    )

    redis = bool(settings.REDIS_URL)
    add(
        "Platform",
        "jobs",
        "Background jobs & daily reminders",
        "ok" if redis else "warn",
        "Celery + beat via Redis."
        if redis
        else "No Redis: jobs run in-process and plan/study reminders only send if you schedule "
        "`manage.py send_plan_reminders` and `send_study_reminders` (cron) — Docker does this for you.",
    )
    media_ok = os.access(settings.MEDIA_ROOT, os.W_OK) or os.access(
        os.path.dirname(str(settings.MEDIA_ROOT)), os.W_OK
    )
    add(
        "Platform",
        "media",
        "Image storage",
        "ok" if media_ok else "error",
        f"{settings.MEDIA_ROOT} {'is writable' if media_ok else 'is NOT writable'}.",
    )
    engine = settings.DATABASES["default"]["ENGINE"]
    add(
        "Platform",
        "db",
        "Database",
        "ok" if "postgres" in engine else "warn",
        "PostgreSQL."
        if "postgres" in engine
        else "SQLite — fine for development, use PostgreSQL in production (Docker does).",
    )

    add(
        "Security",
        "debug",
        "Debug mode",
        "ok" if not settings.DEBUG else "warn",
        "Off." if not settings.DEBUG else "ON — never run production with DJANGO_DEBUG=true.",
    )
    add(
        "Security",
        "secret",
        "Django secret key",
        "ok" if not settings.SECRET_KEY.startswith("dev-insecure") else "warn",
        "Custom."
        if not settings.SECRET_KEY.startswith("dev-insecure")
        else "Using the development key — set DJANGO_SECRET_KEY.",
    )
    add(
        "Security",
        "fernet",
        "Key encryption secret",
        "ok" if settings.AASAN_SECRETS_KEY else "error",
        "Set."
        if settings.AASAN_SECRETS_KEY
        else "AASAN_SECRETS_KEY not set — API keys can't be saved. Run setup_env or set it in api/.env.",
    )
    add(
        "Security",
        "hosts",
        "Allowed hosts",
        "ok" if "*" not in settings.ALLOWED_HOSTS else "error",
        ", ".join(settings.ALLOWED_HOSTS)[:200],
    )
    https = settings.FRONTEND_URL.startswith("https://")
    add(
        "Security",
        "https",
        "HTTPS",
        "ok" if https else "warn",
        settings.FRONTEND_URL
        + ("" if https else " — use HTTPS in production (cookies, camera and mic need it)."),
    )
    if https:
        hsts = getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0
        add(
            "Security",
            "hsts",
            "HTTPS-only (HSTS)",
            "ok" if hsts >= 31536000 else "warn",
            f"{hsts} seconds."
            + (
                ""
                if hsts >= 31536000
                else " Raise DJANGO_HSTS_SECONDS to 31536000 once HTTPS works everywhere."
            ),
        )
    add(
        "Platform",
        "monitoring",
        "Error monitoring",
        "ok" if os.environ.get("SENTRY_DSN") else "warn",
        "Sentry is on (no personal data is sent)."
        if os.environ.get("SENTRY_DSN")
        else "SENTRY_DSN not set — production errors only reach the server logs.",
    )
    from django.contrib.auth import get_user_model

    from apps.accounts.staff import roles_of

    users = get_user_model().objects
    test_accounts = (
        Q(email__endswith="@aasan.test")
        | Q(email__endswith="@validate.aasan.local")
        | Q(email__startswith="e2e-", email__endswith="@example.com")
        | Q(email__startswith="smoke-", email__endswith="@example.com")
    )
    demo = users.filter(test_accounts).count()
    add(
        "Security",
        "demo",
        "Demo / test accounts",
        "ok" if not demo else ("info" if settings.DEBUG else "warn"),
        "None."
        if not demo
        else f"{demo} demo, test or validation accounts exist (@aasan.test, @validate.aasan.local, e2e-/smoke- "
        "@example.com) — delete them before going live.",
    )
    staff = list(users.filter(Q(is_staff=True) | Q(is_superuser=True), is_active=True))
    supers = sum(1 for u in staff if "superadmin" in roles_of(u))
    add(
        "Security",
        "admins",
        "Admin console staff",
        "ok" if supers <= 3 else "warn",
        f"{len(staff)} staff account{'' if len(staff) == 1 else 's'}, {supers} superadmin{'' if supers == 1 else 's'}."
        + (" Keep superadmins to a few; give others the narrowest role." if supers > 3 else ""),
        "/admin/staff",
    )

    order = {"error": 0, "warn": 1, "info": 2, "ok": 3}
    return Response(
        {"items": items, "summary": {s: sum(1 for i in items if i["status"] == s) for s in order}}
    )
