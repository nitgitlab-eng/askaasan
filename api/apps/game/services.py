"""Reward engine. Every award is idempotent on (user, kind, ref) so retries,
re-completions and double-clicks never pay twice."""

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone

from .catalog import (
    BADGES,
    COINS,
    STREAK_REPAIR_DAYS,
    STREAK_REPAIR_PRICE,
    STREAK_REVIVE_GOAL,
    STREAK_REVIVE_HOURS,
    STREAK_REVIVE_KINDS,
    XP,
    level_for,
)
from .models import Notification, PlayerStats, UserBadge, XPEvent


def stats_for(user) -> PlayerStats:
    s, _ = PlayerStats.objects.get_or_create(user=user)
    return s


def _lang(user) -> str:
    return "ta" if getattr(user.profile, "language", "en") == "ta" else "en"


def notify(user, kind, title, body="", link=""):
    Notification.objects.create(user=user, kind=kind, title=title[:160], body=body[:300], link=link[:200])


def grant_badge(user, code) -> bool:
    if code not in BADGES:
        return False
    try:
        with transaction.atomic():
            UserBadge.objects.create(user=user, code=code)
    except IntegrityError:
        return False
    b, lang = BADGES[code], _lang(user)
    s = stats_for(user)
    PlayerStats.objects.filter(pk=s.pk).update(coins=F("coins") + COINS["badge"])
    title = f"{b['icon']} {b[lang]}"
    notify(user, "badge", title, b[f"desc_{lang}"], "/achievements")
    return True


def _paused_between(user_id, start, end) -> bool:
    from apps.study.planner import all_paused

    return all_paused(user_id, start, end)


def streak_alive(s: PlayerStats, today) -> bool:
    """Active today or yesterday, or a freeze can bridge the one missed day, or the gap was all away-mode days."""
    if not s.last_active:
        return False
    gap = (today - s.last_active).days
    if gap <= 1 or (gap == 2 and s.freezes > 0):
        return True
    return _paused_between(s.user_id, s.last_active + timedelta(days=1), today - timedelta(days=1))


def _record_break(s: PlayerStats, today, now=None) -> None:
    """Remember a lost streak (2+ days) so it can be repaired; the free revival window starts now."""
    s.last_streak = s.streak
    s.broken_at = today
    s.revive_started_at = now or timezone.now()


def _break_recorded(s: PlayerStats) -> bool:
    """The current lapse was already recorded (a break noticed after the last activity). The row keeps its streak
    until the next activity, so an away-mode pause added afterwards can still keep it alive."""
    return bool(s.broken_at and (not s.last_active or s.broken_at > s.last_active))


def _touch_streak(s: PlayerStats, today, now=None) -> list[str]:
    """Advance the daily streak; spend a freeze to bridge exactly one missed day."""
    events = []
    if s.last_active == today:
        return events
    if s.last_active == today - timedelta(days=1):
        s.streak += 1
    elif s.last_active and _paused_between(
        s.user_id, s.last_active + timedelta(days=1), today - timedelta(days=1)
    ):
        s.streak += 1  # away mode: the gap was a planned pause
        events.append("pause_protected")
    elif s.last_active == today - timedelta(days=2) and s.freezes > 0:
        s.freezes -= 1
        s.streak += 1
        events.append("freeze_used")
    else:
        if s.streak >= 2 and not _break_recorded(s):
            _record_break(s, today, now)
            events.append("streak_broken")
        s.streak = 1
    s.best_streak = max(s.best_streak, s.streak)
    s.last_active = today
    events.append("streak")
    return events


# ── Streak repair ──


class RepairError(Exception):
    def __init__(self, code: str, status: int, **extra):
        super().__init__(code)
        self.code, self.status, self.extra = code, status, extra


def _repair_ref(s: PlayerStats) -> str:
    return f"repair:{s.broken_at.isoformat()}"


def _offer_open(s: PlayerStats, today) -> bool:
    return bool(
        s.broken_at
        and s.last_streak >= 2
        and 0 <= (today - s.broken_at).days <= STREAK_REPAIR_DAYS
        # Closed if the streak carried on after all (a pause added later) or the new run already caught up.
        and not (s.streak >= s.last_streak and streak_alive(s, today))
        and not XPEvent.objects.filter(user_id=s.user_id, kind="streak_repair", ref=_repair_ref(s)).exists()
    )


def _revive_progress(s: PlayerStats) -> int:
    if not s.revive_started_at:
        return 0
    return XPEvent.objects.filter(
        user_id=s.user_id,
        kind__in=STREAK_REVIVE_KINDS,
        created_at__gte=s.revive_started_at,
        created_at__lte=s.revive_started_at + timedelta(hours=STREAK_REVIVE_HOURS),
    ).count()


def _sync_break(s: PlayerStats, today, now) -> bool:
    """The lazy ("virtual") break: the row still shows a streak the calendar has already ended. Record it, so the
    repair offer shows before the first activity, and open the revival window. Caller holds the row lock."""
    changed = False
    if s.streak >= 2 and not _break_recorded(s) and not streak_alive(s, today):
        _record_break(s, today, now)
        changed = True
    if s.revive_started_at is None and _offer_open(s, today):
        s.revive_started_at = now
        changed = True
    return changed


def detect_break(user, now=None) -> PlayerStats:
    """Cheap check on every status read; takes the row lock only when there is something to record. `now` lets
    scheduled callers (accounts.stepup) and tests pin the clock."""
    s = stats_for(user)
    now = now or timezone.now()
    today = timezone.localdate(now)
    if not (
        (s.streak >= 2 and not _break_recorded(s) and not streak_alive(s, today))
        or (s.revive_started_at is None and s.broken_at and _offer_open(s, today))
    ):
        return s
    with transaction.atomic():
        s = PlayerStats.objects.select_for_update().get(pk=s.pk)
        if _sync_break(s, today, now):
            s.save(update_fields=["last_streak", "broken_at", "revive_started_at"])
    return s


def lapse_streak(s: PlayerStats) -> int:
    """The streak a lapsed learner had when they stopped (the row keeps it until their next activity)."""
    return s.streak


def winback_offer(user) -> int:
    """A comeback email is about to promise "revive your streak": record the break now (if it wasn't yet) or move an
    unused offer to today, so the 7-day repair window starts with the email; the 72-hour revival window starts when
    they come back. Under the row lock. → the streak that can come back (0 = no offer)."""
    with transaction.atomic():
        s = PlayerStats.objects.select_for_update().filter(user=user).first()
        if not s:
            return 0
        today = timezone.localdate()
        if s.streak >= 2 and not _break_recorded(s) and not streak_alive(s, today):
            _record_break(s, today)
        elif (
            s.broken_at
            and s.last_streak >= 2
            and not XPEvent.objects.filter(user=user, kind="streak_repair", ref=_repair_ref(s)).exists()
        ):
            s.broken_at = today
        else:
            return 0
        s.revive_started_at = None
        s.save(update_fields=["last_streak", "broken_at", "revive_started_at"])
        return s.last_streak


def repair_offer(s: PlayerStats, today=None) -> dict | None:
    today = today or timezone.localdate()
    if not _offer_open(s, today):
        return None
    ends = s.revive_started_at + timedelta(hours=STREAK_REVIVE_HOURS) if s.revive_started_at else None
    return {
        "last_streak": s.last_streak,
        "broken_at": s.broken_at,
        "expires_on": s.broken_at + timedelta(days=STREAK_REPAIR_DAYS),
        "price": STREAK_REPAIR_PRICE,
        "revive_goal": STREAK_REVIVE_GOAL,
        "revive_progress": min(_revive_progress(s), STREAK_REVIVE_GOAL),
        "revive_ends_at": ends,
        "revive_open": bool(ends and timezone.now() <= ends),
    }


def _apply_repair(user, s: PlayerStats, how: str, today) -> dict | None:
    """Restore the lost streak (plus the days since, if the new run is still alive). Caller holds the row lock.
    Idempotent on (user, "streak_repair", "repair:<broken_at>"): a second call returns None."""
    price = STREAK_REPAIR_PRICE if how == "coins" else 0
    try:
        with transaction.atomic():
            XPEvent.objects.create(
                user=user, kind="streak_repair", ref=_repair_ref(s), xp=0, coins=-price, day=today
            )
    except IntegrityError:
        return None
    alive = streak_alive(s, today)
    s.streak = s.last_streak + (s.streak if alive else 0)
    if not alive:
        s.last_active = today - timedelta(days=1)  # today's first activity carries it on
    s.coins -= price
    s.best_streak = max(s.best_streak, s.streak)
    s.revive_started_at = None
    s.save()
    badges = [code for n, code in ((3, "streak_3"), (7, "streak_7"), (30, "streak_30")) if s.streak >= n]
    badges = [code for code in badges if grant_badge(user, code)]
    lang = _lang(user)
    notify(
        user,
        "streak",
        "🔥 "
        + (f"உங்கள் {s.streak} நாள் தொடர் மீண்டது!" if lang == "ta" else f"Your {s.streak}-day streak is back!"),
        link="/achievements",
    )
    return {"streak": s.streak, "how": how, "badges": badges}


def repair_streak(user, how: str) -> dict:
    """Repair a broken streak with coins or a finished revival. Raises RepairError(code, http status)."""
    if how not in ("coins", "revive"):
        raise RepairError("bad_how", 400)
    err, out = None, None
    with transaction.atomic():
        today, now = timezone.localdate(), timezone.now()
        s = PlayerStats.objects.select_for_update().get_or_create(user=user)[0]
        if _sync_break(s, today, now):
            s.save(update_fields=["streak", "last_streak", "broken_at", "revive_started_at"])
        if (
            s.broken_at
            and XPEvent.objects.filter(user=user, kind="streak_repair", ref=_repair_ref(s)).exists()
        ):
            err = RepairError("already_repaired", 409)
        elif not _offer_open(s, today):
            err = RepairError("no_offer", 404)
        elif how == "coins" and s.coins < STREAK_REPAIR_PRICE:
            err = RepairError("not_enough_coins", 402, price=STREAK_REPAIR_PRICE)
        elif how == "revive" and (p := _revive_progress(s)) < STREAK_REVIVE_GOAL:
            err = RepairError("revive_incomplete", 400, progress=p, goal=STREAK_REVIVE_GOAL)
        else:
            out = _apply_repair(user, s, how, today)
            if out is None:
                err = RepairError("already_repaired", 409)
    if err:
        raise err
    return out


def daily_goal_xp(user) -> int:
    from apps.accounts.preferences import upgrade

    minutes = upgrade(user.preferences.data)["learning"]["daily_goal_minutes"]
    return max(20, minutes * 4)  # ~4 XP per focused minute


@transaction.atomic
def award(user, kind: str, ref: str = "", xp: int | None = None, coins: int | None = None) -> dict:
    """Credit XP/coins once per (kind, ref). Returns what changed for the UI."""
    xp = XP.get(kind, 0) if xp is None else xp
    coins = COINS.get(kind, 0) if coins is None else coins
    today = timezone.localdate()
    now = timezone.now()  # before the XPEvent below, so a revival window opened by this award counts it
    # Lock the stats row first, then claim the (user, kind, ref) key under that lock. The unique
    # constraint on XPEvent is the backstop if two requests still race.
    s = PlayerStats.objects.select_for_update().get_or_create(user=user)[0]
    fields = {"xp": xp, "coins": coins, "day": today}
    if ref:
        try:
            with transaction.atomic():
                _, created = XPEvent.objects.get_or_create(user=user, kind=kind, ref=ref, defaults=fields)
        except IntegrityError:
            created = False
        if not created:
            return {"xp": 0, "coins": 0, "duplicate": True}
    else:
        XPEvent.objects.create(user=user, kind=kind, ref=ref, **fields)
    before_level = level_for(s.xp)
    streak_events = _touch_streak(s, today, now)
    if s.revive_started_at is None and _offer_open(s, today):  # came back with a repair offer pending
        s.revive_started_at = now
    s.xp += xp
    s.coins += coins
    s.save()
    from apps.accounts.cadence import on_activity

    on_activity(user.id)  # studying again puts backed-off reminders back to normal (one indexed UPDATE)
    out = {"xp": xp, "coins": coins, "level_up": None, "badges": [], "streak": s.streak, "daily_goal": False}
    # Free streak revival: enough lessons / Today circuits inside the window repairs the streak on the spot.
    if (
        kind in STREAK_REVIVE_KINDS
        and s.revive_started_at
        and now <= s.revive_started_at + timedelta(hours=STREAK_REVIVE_HOURS)
        and _offer_open(s, today)
        and _revive_progress(s) >= STREAK_REVIVE_GOAL
    ):
        repaired = _apply_repair(user, s, "revive", today)
        if repaired:
            out["streak_repaired"] = repaired
            out["streak"] = s.streak
            out["badges"].extend(repaired["badges"])

    after_level = level_for(s.xp)
    lang = _lang(user)
    if after_level > before_level:
        out["level_up"] = after_level
        notify(
            user, "level_up", f"⭐ {'நிலை' if lang == 'ta' else 'Level'} {after_level}!", link="/achievements"
        )
        if after_level >= 5 and grant_badge(user, "level_5"):
            out["badges"].append("level_5")
    if "freeze_used" in streak_events:
        notify(
            user,
            "streak",
            "🧊 "
            + (
                "Streak freeze உங்கள் தொடரைக் காப்பாற்றியது!"
                if lang == "ta"
                else "A streak freeze saved your streak!"
            ),
        )
    for n, code in ((3, "streak_3"), (7, "streak_7"), (30, "streak_30")):
        if s.streak >= n and grant_badge(user, code):
            out["badges"].append(code)

    # Daily goal: first time today's XP crosses the target.
    if kind != "daily_goal":
        today_xp = XPEvent.objects.filter(user=user, day=today).aggregate(t=Sum("xp"))["t"] or 0
        if (
            today_xp >= daily_goal_xp(user)
            and not XPEvent.objects.filter(user=user, kind="daily_goal", ref=str(today)).exists()
        ):
            bonus = award(user, "daily_goal", ref=str(today))
            out["daily_goal"] = True
            out["xp"] += bonus["xp"]
            out["coins"] += bonus["coins"]
    return out


def on_activity(user, activity, score: float, first_try: bool) -> dict:
    if score >= 0.7:
        return award(
            user,
            "activity_correct",
            ref=f"act:{activity.id}",
            xp=XP["activity_correct"] + (5 if first_try and score >= 0.999 else 0),
        )
    if score > 0:
        return award(user, "activity_partial", ref=f"actp:{activity.id}")
    return {"xp": 0, "coins": 0}


def on_lesson_complete(user, subsection, score: float) -> dict:
    out = award(user, "lesson_complete", ref=f"lesson:{subsection.id}")
    badges = list(out.get("badges", []))
    if score >= 0.999:
        bonus = award(user, "lesson_perfect_bonus", ref=f"perfect:{subsection.id}")
        out["xp"] += bonus["xp"]
        out["coins"] += bonus["coins"]
        if grant_badge(user, "perfect_lesson"):
            badges.append("perfect_lesson")
    if grant_badge(user, "first_lesson"):
        badges.append("first_lesson")
    from apps.learning.models import Subsection, UserSubsectionState

    cur = subsection.section.curriculum
    visible = Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False)
    total = visible.count()
    done = UserSubsectionState.objects.filter(user=user, subsection__in=visible, status="completed").count()
    if total and done >= total and grant_badge(user, "course_complete"):
        badges.append("course_complete")
    out["badges"] = badges
    return out


def on_review(user, card) -> dict:
    from apps.review.models import ReviewLog

    out = award(user, "review_card", ref=f"rev:{card.id}:{timezone.localdate()}")
    if ReviewLog.objects.filter(card__user=user).count() >= 25 and grant_badge(user, "reviewer"):
        out.setdefault("badges", []).append("reviewer")
    return out


def week_start(d=None):
    d = d or timezone.localdate()
    return d - timedelta(days=d.weekday())


def weekly_xp(user) -> int:
    return XPEvent.objects.filter(user=user, day__gte=week_start()).aggregate(t=Sum("xp"))["t"] or 0


REFERRAL_CAP = 20  # most invites one account can be paid for


def credit_referral(new_user, code: str) -> bool:
    """Link a new account to its inviter. Coins wait until the new account proves its email (pay_referral)."""
    inviter = PlayerStats.objects.filter(referral_code=code).select_related("user").first()
    if not inviter or inviter.user_id == new_user.id:
        return False
    mine = stats_for(new_user)
    if mine.referred_by_id:
        return False
    mine.referred_by = inviter.user
    mine.save(update_fields=["referred_by"])
    if new_user.email_verified:
        pay_referral(new_user)
    return True


def pay_referral(new_user) -> bool:
    """Both friends get coins once the invited account is verified; the inviter is paid for at most REFERRAL_CAP."""
    mine = PlayerStats.objects.filter(user=new_user).select_related("referred_by").first()
    if not mine or not mine.referred_by_id or not new_user.email_verified:
        return False
    inviter = mine.referred_by
    if award(new_user, "referral", ref=f"joined:{inviter.id}", xp=0).get("duplicate"):
        return False
    paid = XPEvent.objects.filter(user=inviter, kind="referral", ref__startswith="invited:").count()
    if paid >= REFERRAL_CAP:
        return True
    award(inviter, "referral", ref=f"invited:{new_user.id}", xp=0)
    lang = _lang(inviter)
    notify(
        inviter,
        "referral",
        "🤝 " + ("உங்கள் நண்பர் சேர்ந்தார்! +100 நாணயங்கள்" if lang == "ta" else "Your friend joined! +100 coins"),
    )
    grant_badge(inviter, "friend")
    return True


def nudges(user) -> list[dict]:
    """Proactive, gentle mentor nudges shown by Kili when the learner opens the app."""
    from apps.accounts.preferences import upgrade
    from apps.review.models import ReviewCard

    if not upgrade(user.preferences.data)["notifications"]["kili_nudges"]:
        return []
    lang = _lang(user)
    out = []
    due = ReviewCard.objects.filter(user=user, due__lte=timezone.now()).count()
    if due:
        out.append(
            {
                "kind": "review_due",
                "link": "/review",
                "text": (
                    f"{due} அட்டைகள் மீள்பார்வைக்குக் காத்திருக்கின்றன — 5 நிமிடம் போதும்!"
                    if lang == "ta"
                    else (f"{due} card is ready" if due == 1 else f"{due} cards are ready")
                    + " for review — 5 minutes is enough!"
                ),
            }
        )
    s = stats_for(user)
    today = timezone.localdate()
    from apps.study.planner import paused_on

    if (
        s.streak >= 2
        and s.last_active == today - timedelta(days=1)
        and timezone.localtime().hour >= 17
        and not paused_on(user.id, today)
    ):
        out.append(
            {
                "kind": "streak_risk",
                "link": "/learn",
                "text": (
                    f"உங்கள் {s.streak} நாள் தொடரைக் காப்பாற்ற ஒரு சிறிய பாடம்! 🔥"
                    if lang == "ta"
                    else f"One small lesson keeps your {s.streak}-day streak alive! 🔥"
                ),
            }
        )
    nxt = 50 * (level_for(s.xp)) ** 2
    if 0 < nxt - s.xp <= 40:
        out.append(
            {
                "kind": "near_level",
                "link": "/learn",
                "text": (
                    f"அடுத்த நிலைக்கு {nxt - s.xp} XP மட்டுமே!"
                    if lang == "ta"
                    else f"Only {nxt - s.xp} XP to your next level!"
                ),
            }
        )
    return out[:2]
