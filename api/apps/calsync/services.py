"""Re-plan study blocks around the learner's real calendar (read-only free/busy for the next 14 days)."""

import logging
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from . import oauth
from .models import CalendarConnection

log = logging.getLogger(__name__)

HORIZON_DAYS = 14
WINDOW = (6 * 60, 22 * 60)  # study only between 06:00 and 22:00 local
BUFFER = 10  # minutes kept free either side of a meeting
STEP = 15
NEAR = 180  # first look within ±3h of a preferred time


def _mins(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _free(busy: list[tuple[int, int]], s: int, need: int) -> bool:
    return all(s + need <= b0 or s >= b1 for b0, b1 in busy)


def find_slot(
    busy: list[tuple[int, int]], need: int, preferred: list[int], earliest: int = 0, window=WINDOW
) -> int | None:
    """Start minute for `need` free minutes. Tries each preferred time, then the nearest times around it
    (later first), then the closest free slot anywhere in the study window. Busy = [(start_min, end_min)] already buffered."""
    lo, hi = max(window[0], earliest), window[1]

    def ok(s):
        return lo <= s and s + need <= hi and _free(busy, s, need)

    for p in preferred:
        for d in range(0, NEAR + 1, STEP):
            for s in (p + d, p - d) if d else (p,):
                if ok(s):
                    return s
    # Nothing near a preferred time: the free slot closest to one (later wins a tie).
    first = lo + (-lo) % STEP
    free = [s for s in range(first, hi - need + 1, STEP) if ok(s)]
    if not free:
        return None
    return min(free, key=lambda s: (min(abs(s - p) for p in preferred) if preferred else 0, -s))


def busy_by_day(intervals: list[tuple[datetime, datetime]]) -> dict[date, list[tuple[int, int]]]:
    """Split aware intervals into local-day minute ranges (with a buffer)."""
    out: dict[date, list[tuple[int, int]]] = defaultdict(list)
    for s, e in intervals:
        s, e = timezone.localtime(s), timezone.localtime(e)
        if e <= s:
            continue
        d = s.date()
        while d <= e.date():
            day_start = 0 if d > s.date() else s.hour * 60 + s.minute
            day_end = 24 * 60 if d < e.date() else e.hour * 60 + e.minute + (1 if e.second else 0)
            if day_end > day_start:
                out[d].append((max(0, day_start - BUFFER), min(24 * 60, day_end + BUFFER)))
            d += timedelta(days=1)
    return out


def fetch_busy(user, start: datetime, end: datetime) -> tuple[list[tuple[datetime, datetime]], list[str]]:
    """Busy intervals from every connected calendar. Returns (intervals, providers that need reconnecting)."""
    intervals, broken = [], []
    for conn in CalendarConnection.objects.filter(user=user):
        app = oauth.app_for(conn.provider)
        if not app:
            continue
        try:
            tok = oauth.refresh(app, conn.token())
            if tok.get("refresh_token") and tok["refresh_token"] != conn.token():
                conn.set_token(tok["refresh_token"])
            intervals += oauth.busy(app, tok["access_token"], start, end)
            conn.last_synced_at, conn.needs_reconnect = timezone.now(), False
            conn.save(update_fields=["encrypted_refresh_token", "last_synced_at", "needs_reconnect"])
        except oauth.CalendarError as e:
            log.info("calendar read failed for user %s (%s): %s", user.id, conn.provider, e.code)
            if e.code == "reconnect":
                conn.needs_reconnect = True
                conn.save(update_fields=["needs_reconnect"])
            broken.append(conn.provider)
    return intervals, broken


def replan(user, now: datetime | None = None) -> dict:
    """Move the planner's own (auto) study blocks for the next 14 days into free gaps near the learner's preferred times.
    Learner-made blocks stay where they are and count as busy. Never writes to the learner's calendar."""
    from apps.study.models import StudyBlock
    from apps.study.planner import _prefs, ensure_blocks

    now = timezone.localtime(now or timezone.now())
    today = now.date()
    ensure_blocks(user, today, HORIZON_DAYS)
    start = timezone.make_aware(datetime.combine(today, time.min))
    intervals, broken = fetch_busy(user, start, start + timedelta(days=HORIZON_DAYS))
    by_day = busy_by_day(intervals)
    prefs = _prefs(user)
    preferred = [_mins(t) for t in (prefs.get("reminder_times") or ["19:00"])]

    blocks = list(
        StudyBlock.objects.filter(
            user=user, date__gte=today, date__lt=today + timedelta(days=HORIZON_DAYS)
        ).exclude(status="skipped")
    )
    moved = kept = unplaced = 0
    for d in sorted({b.date for b in blocks}):
        day = [b for b in blocks if b.date == d]
        fixed = [b for b in day if not b.auto or b.status != "planned"]
        movable = sorted((b for b in day if b.auto and b.status == "planned"), key=lambda b: b.start)
        if not movable:
            continue
        busy = by_day.get(d, []) + [(_mins(b.start), _mins(b.start) + b.minutes) for b in fixed]
        need = sum(b.minutes for b in movable)
        earliest = now.hour * 60 + now.minute + STEP if d == today else 0
        slot = find_slot(busy, need, preferred, earliest)
        if slot is None:
            unplaced += len(movable)
            continue
        for b in movable:  # keep the day's blocks back-to-back (revision first, then the lesson)
            if b.start != _hhmm(slot):
                b.start = _hhmm(slot)
                b.save(update_fields=["start"])
                moved += 1
            else:
                kept += 1
            slot += b.minutes
    return {
        "moved": moved,
        "kept": kept,
        "unplaced": unplaced,
        "busy": len(intervals),
        "needs_reconnect": broken,
        "synced_at": timezone.now(),
    }
