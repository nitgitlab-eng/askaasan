"""Step up after a miss (Celery beat `stepup-checks`, every 15 minutes; acts at each learner's nudge time).

With last_active = D, the evening check warns on D+1 ("your streak ends tonight"). If the day is still missed, the
streak break is noticed on D+2:
- Streak learners (2+ days): break detection first (`game.services.detect_break`, which records the break and opens
  the free revival window), then the repair offer; nothing if the offer is closed or used. The day the break was
  noticed → `streak_lost_1` (to /achievements?repair=1); the next day → `streak_lost_2` with the hours left.
- Learners without a streak: one `missed_day` nudge on D+2, only if D+1 was one of their study days.
Day 3 of the lapse is also win-back day 3 (winback.py): the win-back email still goes, its push and bell yield to
step-up.

Candidates: active, with a push device, last studied 2-4 days ago, not in away mode, reminders not paused. Bell + push
in the companion's voice (voice.py). Idempotent through WinbackSend(kind="stepup_1"|"stepup_2", episode=the day the
break was noticed, or the last active day) claimed before sending."""

import logging
import math
from datetime import datetime, time, timedelta

from django.utils import timezone

from . import cadence

log = logging.getLogger(__name__)

MIN_GAP, MAX_GAP = 2, 4
REPAIR_LINK = "/achievements?repair=1"


def _hours_left(offer: dict, now) -> int:
    if offer.get("revive_open") and offer.get("revive_ends_at"):
        end = offer["revive_ends_at"]
    else:  # the coins repair stays open until the end of `expires_on`
        end = timezone.make_aware(datetime.combine(offer["expires_on"] + timedelta(days=1), time.min))
    return max(1, math.ceil((end - now).total_seconds() / 3600))


def _studies_on(prefs: dict, day) -> bool:
    return day.weekday() in prefs["learning"]["study_days"]


def supersedes_study(user, s, today, prefs: dict | None = None) -> bool:
    """A streak-risk or step-up nudge owns today's push, so the daily study reminder sends only email + bell."""
    from apps.game.services import streak_alive

    from .preferences import upgrade

    if not s or not s.last_active:
        return False
    gap = (today - s.last_active).days
    if gap == 1:
        return s.streak >= 2
    if MIN_GAP <= gap <= MAX_GAP - 1:
        if s.streak >= 2:
            return not streak_alive(s, today)
        prefs = prefs or upgrade(user.preferences.data)
        return gap == MIN_GAP and _studies_on(prefs, today - timedelta(days=1))
    return False


def _decide(user, s, prefs, today, now):
    """→ (claim kind, episode, moment, push kind, link, context) or None."""
    from apps.game.services import detect_break, repair_offer

    if s.streak >= 2:
        s = detect_break(user, now)
        offer = repair_offer(s, today)
        if not offer:
            return None
        day = (today - offer["broken_at"]).days
        if day == 0:
            return (
                "stepup_1",
                offer["broken_at"],
                "streak_lost_1",
                "streak",
                REPAIR_LINK,
                {"n": offer["last_streak"]},
            )
        if day == 1:
            ctx = {"n": offer["last_streak"], "hours": _hours_left(offer, now)}
            return "stepup_2", offer["broken_at"], "streak_lost_2", "streak", REPAIR_LINK, ctx
        return None
    if (today - s.last_active).days == MIN_GAP and _studies_on(prefs, today - timedelta(days=1)):
        return "stepup_1", s.last_active, "missed_day", "study", "/today", {}
    return None


def run(now=None) -> dict:
    from apps.game.models import PlayerStats
    from apps.game.services import notify
    from apps.study.planner import paused_on

    from . import besttime, push, voice
    from .models import PushSubscription
    from .preferences import upgrade
    from .winback import _claim

    now = now or timezone.now()
    out = {"streak_lost_1": 0, "streak_lost_2": 0, "missed_day": 0}
    if not push.enabled():
        return out
    today = cadence.local_now(None, now).date()
    rows = (
        PlayerStats.objects.filter(
            last_active__gte=today - timedelta(days=MAX_GAP),
            last_active__lte=today - timedelta(days=MIN_GAP),
            user__is_active=True,
            user__in=PushSubscription.objects.values("user"),
        )
        .exclude(user__age_band="minor")
        .select_related(  # no streak-pressure pushes to under-18s (DPDP Act s.9)
            "user__profile", "user__preferences", "user__reminder_state"
        )
    )
    for s in rows:
        u = s.user
        try:
            minute = cadence.local_minute(u, now)
            prefs = upgrade(u.preferences.data)
            if not cadence.daytime(minute) or minute < besttime.nudge_minute(u, prefs, cadence.state_of(u)):
                continue
            if (today - s.last_active).days > MAX_GAP or paused_on(u.id, today):
                continue
            plan = _decide(u, s, prefs, today, now)
            if not plan:
                continue
            claim, episode, moment, kind, link, ctx = plan
            if not cadence.allowed(u, kind, moment, now) or not _claim(u, claim, episode):
                continue
            msg = voice.pick(u, moment, **ctx)
            notify(u, "stepup", msg.title, msg.body, link)
            push.send(u, kind, msg.title, msg.body, link, moment=moment, variant=msg.variant)
            out[moment] += 1
        except Exception:
            log.exception("stepup: user %s failed", u.id)
    return out
