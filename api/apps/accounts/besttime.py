"""The time a learner usually studies, learned from when their first activity of the day happens.

Nightly (`compute_all`, from `tasks.reminder_nightly`): one query over the last WINDOW of XPEvents (the first event of
each active day); with MIN_DAYS or more active days, `best_minute` is the median local minute of those first events,
otherwise None.

- `base_minute`: the learned time → the learner's first reminder time → 19:00.
- `nudge_minute`: LEAD minutes before the base, kept inside EARLIEST..LATEST (system-timed pushes never 22:00-08:00).
- The daily study reminder goes at exactly the chosen time when the learner picked one (`chosen()`), otherwise at
  `nudge_minute` rounded down to the 15-minute beat."""

import statistics
from collections import defaultdict
from datetime import timedelta

from django.db.models import Min
from django.utils import timezone

from .cadence import local_now, state_of

WINDOW = timedelta(days=21)
MIN_DAYS = 5
DEFAULT_TIMES = ["19:00"]
DEFAULT_MINUTE = 19 * 60
LEAD = 30
EARLIEST, LATEST = 8 * 60, 21 * 60 + 30


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def parse(value) -> int | None:
    try:
        h, m = str(value).split(":")
        h, m = int(h), int(m)
    except (TypeError, ValueError):
        return None
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def round_down_15(minute: int) -> int:
    return minute - minute % 15


def learned_minute(first_minutes: list[int]) -> int | None:
    if len(first_minutes) < MIN_DAYS:
        return None
    return round(statistics.median(first_minutes))


def chosen(prefs: dict, st) -> bool:
    """The learner picked their reminder time (the flag set by the preferences PATCH, or any non-default value: only
    the Plan screen writes it)."""
    return bool(st.time_chosen) or prefs["learning"]["reminder_times"] not in ([], DEFAULT_TIMES)


def base_minute(prefs: dict, st) -> int:
    if st.best_minute is not None:
        return st.best_minute
    times = prefs["learning"]["reminder_times"]
    first = parse(times[0]) if times else None
    return DEFAULT_MINUTE if first is None else first


def nudge_minute(user, prefs: dict | None = None, st=None) -> int:
    from .preferences import upgrade

    prefs = prefs or upgrade(user.preferences.data)
    st = st if st is not None else state_of(user)
    return min(max(base_minute(prefs, st) - LEAD, EARLIEST), LATEST)


def study_times(user, prefs: dict, st=None) -> set[str]:
    """ "HH:MM" values at which today's study reminder may go."""
    st = st if st is not None else state_of(user)
    if chosen(prefs, st):
        return set(prefs["learning"]["reminder_times"])
    return {hhmm(round_down_15(nudge_minute(user, prefs, st)))}


def compute_all(now=None) -> dict:
    """Recompute every learner's best time from the last WINDOW of activity in one query, and bulk-write it."""
    from apps.game.models import XPEvent

    from .models import ReminderState

    now = now or timezone.now()
    firsts = defaultdict(list)
    rows = (
        XPEvent.objects.filter(created_at__gte=now - WINDOW)
        .exclude(user__age_band="minor")  # no learned-behaviour profile of under-18s (DPDP Act s.9)
        .values("user_id", "day")
        .annotate(first=Min("created_at"))
        .order_by()
    )
    for r in rows.iterator():
        t = local_now(None, r["first"])
        firsts[r["user_id"]].append(t.hour * 60 + t.minute)
    best = {uid: (learned_minute(m), len(m)) for uid, m in firsts.items()}
    # Everyone with activity, plus anyone whose old estimate should now be cleared.
    existing = {
        st.user_id: st
        for st in ReminderState.objects.filter(user_id__in=list(best)).only(
            "id", "user_id", "best_minute", "best_days"
        )
    }
    stale = ReminderState.objects.exclude(user_id__in=list(best)).filter(best_minute__isnull=False)
    cleared = stale.update(best_minute=None, best_days=0, best_computed_at=now)
    changed, new = [], []
    for uid, (minute, days) in best.items():
        st = existing.get(uid)
        if st is None:
            new.append(ReminderState(user_id=uid, best_minute=minute, best_days=days, best_computed_at=now))
            continue
        st.best_minute, st.best_days, st.best_computed_at = minute, days, now
        changed.append(st)
    ReminderState.objects.bulk_update(
        changed, ["best_minute", "best_days", "best_computed_at"], batch_size=500
    )
    ReminderState.objects.bulk_create(new, batch_size=500, ignore_conflicts=True)
    return {
        "learned": sum(1 for m, _ in best.values() if m is not None),
        "users": len(best),
        "cleared": cleared,
    }
