"""Win-back (daily, Celery beat `winback-daily`).

1. Lapsed learners: exactly 3, 7 or 30 days since they last studied (PlayerStats.last_active). Skipped when the
   account is inactive or unverified, in away mode, opened the app in the last 2 days (User.last_login, touched hourly
   by the token refresh), opted out (`email_winback`) or got any win-back mail in the last 2 days. One personal email
   (the digest card: lost streak, the course they left, reviews due) + bell + push. The 7- and 30-day mails offer to
   revive the streak (only if it was 3+ days) and link to /achievements?repair=1. Bell and push speak in the
   companion's voice (voice.py). Day 3 is also step-up day 2 (stepup.py): when the repair offer is open or step-up
   sent its last nudge, the 3-day win-back sends only the email; step-up claims never count toward the quiet rule.
2. Lapsed plans: a paid plan that ended 3-10 days ago with no renewal, no auto-renew, no school seat and no other
   active plan gets one email with the active `purpose="winback_lapse"` promo code, at most once per 180 days. The code
   is only ever in the email (never in push or the bell).

Idempotent: WinbackSend is unique per (user, kind, episode) and is claimed before anything is sent."""

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Max, Q
from django.utils import timezone

from .voice import _first_name

log = logging.getLogger(__name__)

MILESTONES = {3: "inactive_3", 7: "inactive_7", 30: "inactive_30"}
QUIET = timedelta(days=2)
LAPSE_MIN_DAYS, LAPSE_MAX_DAYS = 3, 10
PROMO_EVERY = timedelta(days=180)
REVIVE_MIN = 3

TXT = {
    "en": {
        "subject_3": "{name}, your lessons miss you 🦜",
        "subject_7": "{name}, it's been a week. Pick up where you left off",
        "subject_30": "{name}, come back to Aasan: 5 minutes is enough",
        "hi_3": "It's been a few days. One short lesson gets you going again:",
        "hi_7": "A week away is fine. Here's the easiest way back in:",
        "hi_30": "It's been a while, and everything you made is still here:",
        "revive": "🔥 Bring back your {n}-day streak (repair it within 7 days)",
        "continue": "▶️ Continue “{title}”",
        "reviews": "🔁 {n} review cards are waiting",
        "start": "📘 Start a 5-minute lesson",
        "bye": "See you soon! — {name}",
        "lapse_subject": "Come back to {plan}: {off} for you",
        "lapse_hi": "Your {plan} ended a few days ago. If you'd like it back, here's {off} with code {code}{until}.",
        "lapse_until": " (valid until {date})",
        "lapse_cta": "💳 See plans",
        "lapse_bell": "A comeback offer for {plan} is in your email",
    },
    "ta": {
        "subject_3": "{name}, உங்கள் பாடங்கள் உங்களை எதிர்பார்க்கின்றன 🦜",
        "subject_7": "{name}, ஒரு வாரம் ஆகிவிட்டது. விட்ட இடத்திலிருந்து தொடருங்கள்",
        "subject_30": "{name}, Aasan-க்கு மீண்டும் வாருங்கள்: 5 நிமிடம் போதும்",
        "hi_3": "சில நாட்கள் ஆகிவிட்டன. ஒரு சிறிய பாடம் போதும், மீண்டும் தொடங்கலாம்:",
        "hi_7": "ஒரு வார இடைவெளி பரவாயில்லை. திரும்பி வர எளிய வழி இதோ:",
        "hi_30": "நீண்ட நாட்கள் ஆகிவிட்டன. நீங்கள் செய்தவை அனைத்தும் அப்படியே இருக்கின்றன:",
        "revive": "🔥 உங்கள் {n} நாள் தொடரை மீட்டெடுங்கள் (7 நாட்களுக்குள்)",
        "continue": "▶️ “{title}” ஐத் தொடருங்கள்",
        "reviews": "🔁 {n} மீள்பார்வை அட்டைகள் காத்திருக்கின்றன",
        "start": "📘 5 நிமிடப் பாடத்தைத் தொடங்குங்கள்",
        "bye": "விரைவில் சந்திப்போம்! — {name}",
        "lapse_subject": "{plan}-க்கு மீண்டும் வாருங்கள்: உங்களுக்கு {off}",
        "lapse_hi": "உங்கள் {plan} சில நாட்களுக்கு முன் முடிந்தது. மீண்டும் வேண்டுமென்றால், {code} குறியீட்டுடன் {off}{until}.",
        "lapse_until": " ({date} வரை)",
        "lapse_cta": "💳 திட்டங்களைப் பாருங்கள்",
        "lapse_bell": "{plan}-க்கான சிறப்புச் சலுகை உங்கள் மின்னஞ்சலில் உள்ளது",
    },
}


def _lang(user) -> str:
    return "ta" if getattr(getattr(user, "profile", None), "language", "en") == "ta" else "en"


def _claim(user, kind: str, episode, promo=None) -> bool:
    from .models import WinbackSend

    try:
        with transaction.atomic():
            WinbackSend.objects.create(user=user, kind=kind, episode=episode, promo=promo)
    except IntegrityError:
        return False
    return True


# ── 1. Lapsed learners ──


def in_progress(user):
    """The lesson the learner started most recently and hasn't finished (or None)."""
    from apps.learning.models import UserSubsectionState

    return (
        UserSubsectionState.objects.filter(user=user, status="in_progress")
        .select_related("subsection__section")
        .order_by("-started_at")
        .first()
    )


def _lines(user, s, kind: str, lang: str, st=None) -> list[tuple[str, str]]:
    from apps.game.services import lapse_streak, winback_offer
    from apps.review.models import ReviewCard

    T = TXT[lang]
    out = []
    if kind != "inactive_3" and lapse_streak(s) >= REVIVE_MIN and (n := winback_offer(user)):
        out.append((T["revive"].format(n=n), "/achievements?repair=1"))
    if st:
        sub = st.subsection
        out.append(
            (
                T["continue"].format(title=sub.title[:80]),
                f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}",
            )
        )
    due = ReviewCard.objects.filter(user=user, due__lte=timezone.now()).count()
    if due:
        out.append((T["reviews"].format(n=due), "/review"))
    if not any(p.startswith("/learn") for _, p in out):
        out.append((T["start"], "/learn"))
    return out


def _stepup_has_it(user, s, today) -> bool:
    """Day 3 of a lapse is also step-up day 2 (stepup.py): when step-up already sent its last nudge, or the streak
    repair offer is open (step-up owns that conversation), the win-back keeps to email."""
    from apps.game.services import repair_offer

    from .models import WinbackSend

    episodes = [d for d in (s.broken_at, s.last_active) if d]
    if WinbackSend.objects.filter(user=user, kind="stepup_2", episode__in=episodes).exists():
        return True
    return repair_offer(s, today) is not None


def _send_inactive(user, s, kind: str, days: int, today=None) -> None:
    from apps.game.services import notify

    from . import push, voice
    from .digest import render
    from .notify import send_optional
    from .preferences import upgrade

    lang = _lang(user)
    T = TXT[lang]
    st = in_progress(user)
    lines = _lines(user, s, kind, lang, st)
    subject = T[f"subject_{days}"].format(name=_first_name(user))
    companion = upgrade(user.preferences.data)["mascot"]["name"]
    text, html = render(lines, T[f"hi_{days}"], T["bye"].format(name=companion))
    send_optional(user, "email_winback", subject, text, html)
    if kind == "inactive_3" and _stepup_has_it(user, s, today or timezone.localdate()):
        return
    _, link = lines[0]
    moment = f"winback_{days}"
    msg = voice.pick(user, moment, course=st.subsection.title if st else None)
    notify(user, "winback", msg.title, msg.body, link)
    push.send(user, "winback", msg.title, msg.body, link, moment=moment, variant=msg.variant)


def inactive(now=None) -> dict:
    from apps.game.models import PlayerStats
    from apps.study.planner import paused_on

    from .models import WinbackSend
    from .notify import wants

    now = now or timezone.now()
    today = timezone.localdate(now)
    out = dict.fromkeys(MILESTONES.values(), 0)
    rows = (
        PlayerStats.objects.filter(
            last_active__in=[today - timedelta(days=n) for n in MILESTONES],
            user__is_active=True,
            user__email_verified=True,
        )
        .filter(Q(user__last_login__isnull=True) | Q(user__last_login__lt=now - QUIET))
        .exclude(user__age_band="minor")  # no behavioural nudges for under-18s (DPDP Act s.9)
        .select_related("user__profile", "user__preferences")
    )
    for s in rows:
        u = s.user
        days = (today - s.last_active).days
        kind = MILESTONES[days]
        try:
            if not wants(u, "email_winback") or paused_on(u.id, today):
                continue
            if (
                WinbackSend.objects.filter(user=u, sent_at__gte=now - QUIET)
                .exclude(kind__startswith="stepup")
                .exists()
            ):
                continue
            if not _claim(u, kind, s.last_active):
                continue
            _send_inactive(u, s, kind, days, today)
            out[kind] += 1
        except Exception:
            log.exception("winback: %s for user %s failed", kind, u.id)
    return out


# ── 2. Lapsed paid plans ──


def lapse_promo(now=None):
    """The newest usable win-back promo code, or None (then no plan-lapse mail goes out)."""
    from apps.billing.models import PromoCode

    now = now or timezone.now()
    return (
        PromoCode.objects.filter(active=True, purpose="winback_lapse")
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .filter(Q(max_uses=0) | Q(uses__lt=F("max_uses")))
        .order_by("-created_at", "-id")
        .first()
    )


def _off(promo) -> str:
    return f"{promo.value}% off" if promo.kind == "percent" else f"₹{promo.value // 100} off"


def _send_lapse(user, plan, promo) -> None:
    from apps.game.services import notify

    from .digest import render
    from .notify import send_optional
    from .preferences import upgrade

    lang = _lang(user)
    T = TXT[lang]
    until = (
        T["lapse_until"].format(date=f"{timezone.localtime(promo.expires_at):%d %b}")
        if promo.expires_at
        else ""
    )
    off = _off(promo)
    subject = T["lapse_subject"].format(plan=plan.name, off=off)
    hi = T["lapse_hi"].format(plan=plan.name, off=off, code=promo.code, until=until)
    companion = upgrade(user.preferences.data)["mascot"]["name"]
    text, html = render([(T["lapse_cta"], "/plans")], hi, T["bye"].format(name=companion))
    send_optional(user, "email_winback", subject, text, html)
    notify(user, "winback", T["lapse_bell"].format(plan=plan.name), link="/plans")  # never the code


def plan_lapse(now=None) -> int:
    from apps.billing.models import Entitlement
    from apps.billing.reminders import _renews
    from apps.billing.services import active_entitlement, seat_plan

    from .models import WinbackSend
    from .notify import wants

    now = now or timezone.now()
    promo = lapse_promo(now)
    if not promo:
        return 0
    ended = (
        Entitlement.objects.filter(
            source="payment",
            ends_at__lte=now - timedelta(days=LAPSE_MIN_DAYS),
            ends_at__gte=now - timedelta(days=LAPSE_MAX_DAYS),
            user__is_active=True,
            user__email_verified=True,
        )
        .exclude(user__age_band="minor")
        .select_related("user__profile", "user__preferences", "plan")
    )  # no promos to minors
    latest = {
        r["user"]: r["m"]
        for r in Entitlement.objects.filter(user__in=ended.values("user"))
        .values("user")
        .annotate(m=Max("ends_at"))
    }
    sent = 0
    for ent in ended:
        u = ent.user
        try:
            if ent.ends_at != latest.get(u.id):  # a later window: renewed, or granted more time
                continue
            if active_entitlement(u) or seat_plan(u) or _renews(u) or not wants(u, "email_winback"):
                continue
            if WinbackSend.objects.filter(user=u, kind="plan_lapse", sent_at__gte=now - PROMO_EVERY).exists():
                continue
            if not _claim(u, "plan_lapse", timezone.localdate(ent.ends_at), promo):
                continue
            _send_lapse(u, ent.plan, promo)
            sent += 1
        except Exception:
            log.exception("winback: plan lapse for user %s failed", u.id)
    return sent


def run(now=None) -> dict:
    return {"inactive": inactive(now), "plan_lapse": plan_lapse(now)}
