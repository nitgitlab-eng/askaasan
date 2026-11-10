"""The live faculty monitor for institution (org) workshop runs: per-learner status classification, the tile each
staff dashboard shows, and the throttled fan-out of tiles to the run's channel group.

Only org runs ever produce tiles: public and staff test runs never reach any dashboard. A learner's tile goes out at
most once every THROTTLE_SECONDS (a cache key per session), whatever triggers it (an action, the 15 s clock, a raised
hand); an urgent update that lands inside the window is sent once the window ends instead of being dropped."""

import asyncio
import re
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.layers import get_channel_layer
from django.core.cache import cache

from . import services
from .models import WorkshopEvent, WorkshopRun, WorkshopSession

THROTTLE_SECONDS = 5
IDLE_AFTER = timedelta(minutes=2)
HELP_WINDOW = timedelta(minutes=5)
STUCK_AFTER = timedelta(minutes=8)
STUCK_AFTER_DIY = timedelta(minutes=10)
REPEAT_HELP_WINDOW = timedelta(minutes=30)
LOW_SCORE = 0.4  # "a low score": two in a row → needs help (a miss is anything under services.PASS)
STUCK_MISSES = 3
RECENT_EVENTS = 80
NUDGE_MAX = 300
_BIDI = frozenset("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")  # direction overrides
# Nudges sent while the learner was offline are shown on their next (re)connect, if this recent.
NUDGE_REPLAY = timedelta(hours=2)

# Status keys, in the order they win when several apply.
STATUSES = (
    "passed",
    "finished",
    "needs_help",
    "getting_ready",
    "stuck",
    "away",
    "idle",
    "overtime",
    "in_grace",
    "doing_diy",
    "engaged",
)
HELP_EVENTS = ("help_screenshot", "help_error")
PROGRESS_EVENTS = (
    "stage_start",
    "concept_done",
    "concept_skipped",
    "answer",
    "diy_step_done",
    "step_skipped",
    "final_attempt",
    "build_test",
    "build_graded",
)
# Learner activity for "idle" (the host finishing a reply counts too: the learner is reading it).
NOT_ACTIVITY = ("tab_hidden", "blur", "idle", "fs_exit", "staff_nudge", "hand_ack")
ATTENTION_EVENTS = ("tab_hidden", "tab_visible", "blur", "focus", "idle", "active", "fs_exit")


def group_name(run_id) -> str:
    return f"wsrun.{run_id}"


def session_group(session_id) -> str:
    return f"wss.{session_id}"


def _iso(dt):
    return dt.isoformat() if dt else None


# ── Classification ───────────────────────────────────────────────────


def _hand_raised(events) -> bool:
    """An unacknowledged raise_hand: the latest raise_hand comes after the latest hand_ack."""
    for e in reversed(events):
        if e.type == "hand_ack":
            return False
        if e.type == "raise_hand":
            return True
    return False


def _norm(summary: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (summary or "").lower()).strip()[:60]


def classify(s, events, now) -> str:
    """One status for the tile (see STATUSES). `events` are the session's recent events, oldest first, and include
    the latest raise_hand / hand_ack (see recent_events). Pure: no queries beyond the session's own fields."""
    if s.passed:
        return "passed"
    if s.status == WorkshopSession.Status.SUBMITTED:
        return "finished"
    # Needs help: a raised hand or a help request in the last 5 minutes (on the prerequisites screen too), or two
    # low scores in a row.
    if _hand_raised(events):
        return "needs_help"
    if any(e.type in HELP_EVENTS and e.created_at >= now - HELP_WINDOW for e in events):
        return "needs_help"
    if not s.started_at:
        return "getting_ready"
    st = services.stage(s) or {}
    diy = st.get("kind") in services.DIY_KINDS
    scored = [e.data.get("score") for e in events if e.type == "answer" and "score" in (e.data or {})]
    if len(scored) >= 2 and all(isinstance(v, int | float) and v < LOW_SCORE for v in scored[-2:]):
        return "needs_help"
    # Stuck: ≥3 misses on the current check, the same help error twice, or no progress for 8 min (10 in DIY).
    items = services.state(s)["items"]
    cursor = services.state(s)["cursor"]
    if st.get("kind") in ("teach", "check") and cursor < len(items):
        it = items[cursor]
        if it.get("tries", 0) >= STUCK_MISSES and (it.get("score") or 0) < services.PASS:
            return "stuck"
    helps = [
        _norm(e.data.get("summary", ""))
        for e in events
        if e.type in HELP_EVENTS and e.created_at >= now - REPEAT_HELP_WINDOW
    ]
    helps = [h for h in helps if h]
    if len(helps) != len(set(helps)):
        return "stuck"
    progress = [e.created_at for e in events if e.type in PROGRESS_EVENTS]
    last_progress = max(progress + [s.started_at])
    if st.get("kind") != "assessment" and now - last_progress > (STUCK_AFTER_DIY if diy else STUCK_AFTER):
        return "stuck"
    # Away: tab hidden right now (only ever recorded with proctoring on, and never during DIY stages).
    if not diy and s.run.effective_proctoring != "off" and (s.stage_state.get("_att") or {}).get("hidden_at"):
        return "away"
    activity = [e.created_at for e in events if e.type not in NOT_ACTIVITY]
    last_active = max([t for t in (s.last_activity_at, s.started_at) if t] + activity)
    if not diy and now - last_active > IDLE_AFTER:
        return "idle"
    label = services.label(s, now)
    if label == WorkshopSession.Status.OVERTIME:
        return "overtime"
    if label == WorkshopSession.Status.IN_GRACE:
        return "in_grace"
    return "doing_diy" if diy else "engaged"


def recent_events(s) -> list:
    """The last RECENT_EVENTS events (oldest first) plus the latest raise_hand / hand_ack if older than that."""
    rows = list(
        WorkshopEvent.objects.filter(session=s).exclude(type="ai_turn").order_by("-id")[:RECENT_EVENTS]
    )
    rows.reverse()
    if not any(e.type in ("raise_hand", "hand_ack") for e in rows):
        last = (
            WorkshopEvent.objects.filter(session=s, type__in=("raise_hand", "hand_ack"))
            .order_by("-id")
            .first()
        )
        if last:
            rows.insert(0, last)
    ai = WorkshopEvent.objects.filter(session=s, type="ai_turn").order_by("-id").first()
    if ai:  # only the latest host reply matters (activity)
        rows.append(ai)
        rows.sort(key=lambda e: (e.created_at, e.id))
    return rows


# ── Tiles ────────────────────────────────────────────────────────────


def learner_out(user, membership=None) -> dict:
    profile = getattr(user, "profile", None)
    name = (getattr(profile, "display_name", "") or "").strip() or user.email.split("@")[0]
    out = {"id": user.id, "name": name}
    roll = ((membership.fields if membership else None) or {}).get("roll_no")
    if roll:
        out["roll_no"] = str(roll)
    return out


def _membership(s):
    from apps.orgs.models import Membership

    return Membership.objects.filter(org_id=s.run.org_id, user_id=s.user_id).first()


def tile(s, now=None, membership="lookup") -> dict:
    """The dashboard tile for one session (JSON-safe: datetimes are ISO strings, for the Redis channel layer)."""
    now = now or services.now()
    events = recent_events(s)
    st = services.stage(s) or {}
    kind = st.get("kind")
    cur = services.state(s) if s.started_at else {"cursor": 0, "items": []}
    texts = services.item_texts(st)
    concept = None
    if s.started_at and kind in ("teach", "check") and texts:
        concept = texts[min(cur["cursor"], len(texts) - 1)]
    diy = {"done": 0, "total": 0}
    if s.started_at and kind in services.DIY_KINDS:
        diy = {"done": sum(1 for it in cur["items"] if it["done"]), "total": len(cur["items"])}
    scores = [v for v in (s.scores or {}).values() if isinstance(v, int | float)]
    proctoring = s.run.effective_proctoring != "off"
    helps = [e for e in events if e.type in HELP_EVENTS][-3:]
    pace = services.pace(s, now)
    if membership == "lookup":
        membership = _membership(s)
    return {
        "session_id": s.id,
        "learner": learner_out(s.user, membership),
        "status": classify(s, events, now),
        "stage": {"index": s.stage_index, "title": st.get("title", ""), "kind": kind or ""},
        "concept": concept,
        "diy": diy,
        "score_so_far": round(sum(scores) / len(scores), 3) if scores else None,
        "final_score": s.final_score,
        "passed": s.passed,
        "attention": {
            "hidden_s": s.hidden_seconds,
            "idle_s": s.idle_seconds,
            "focus_losses": s.focus_losses,
        }
        if proctoring
        else None,
        "help_summaries": [e.data.get("summary", "") for e in reversed(helps)],  # newest first
        "raised_hand": _hand_raised(events),
        "last_activity_at": _iso(s.last_activity_at),
        "pace": pace["status"] if pace else None,
    }


# ── Fan-out ──────────────────────────────────────────────────────────


def _throttle_key(session_id) -> str:
    return f"wsrun:tile:{session_id}"


def publish_tile(session_id) -> bool:
    """Send this learner's tile to the run's monitor group, at most once per THROTTLE_SECONDS. Org runs only.
    → whether it was sent."""
    s = (
        WorkshopSession.objects.select_related("run__workshop", "user__profile")
        .filter(pk=session_id, run__audience=WorkshopRun.Audience.ORG)
        .first()
    )
    if not s:
        return False
    if not cache.add(_throttle_key(session_id), 1, THROTTLE_SECONDS):
        return False
    async_to_sync(get_channel_layer().group_send)(
        group_name(s.run_id), {"type": "wsrun.tile", "tile": tile(s)}
    )
    return True


async def apublish(session_id, *, urgent: bool = False) -> bool:
    """From async code. `urgent` (a raised or acknowledged hand): if the throttle window is still open, send once it
    closes (one deferred send per learner at a time)."""
    sent = await database_sync_to_async(_publish_quiet)(session_id)
    if sent or not urgent:
        return sent
    if cache.add(f"wsrun:tile-soon:{session_id}", 1, THROTTLE_SECONDS + 2):
        asyncio.get_running_loop().create_task(_publish_later(session_id))
    return False


def _publish_quiet(session_id) -> bool:
    try:
        return publish_tile(session_id)
    except Exception:  # the dashboard is best-effort: never break the learner's session over it
        import logging

        logging.getLogger(__name__).exception("workshop tile publish failed for session %s", session_id)
        return False


async def _publish_later(session_id):
    try:
        await asyncio.sleep(THROTTLE_SECONDS + 0.1)
        await database_sync_to_async(_publish_quiet)(session_id)
    finally:
        cache.delete(f"wsrun:tile-soon:{session_id}")


def publish_after_commit(session_id) -> None:
    """For REST views (help, final, start): after the transaction commits, best-effort."""
    from django.db import transaction

    transaction.on_commit(lambda: _publish_quiet(session_id))


# ── Staff actions (called by the monitor consumer after its scope check) ──


def clean_nudge(text) -> tuple[str | None, str | None]:
    """→ (plain text, None) or (None, error code). Control characters become spaces; ≤ NUDGE_MAX characters."""
    if not isinstance(text, str):
        return None, "empty"
    text = "".join(" " if ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0 or ch in _BIDI else ch for ch in text)
    text = re.sub(r" {2,}", " ", text).strip()
    if not text:
        return None, "empty"
    if len(text) > NUDGE_MAX:
        return None, "too_long"
    return text, None


def nudge(session_id, staff, text: str) -> dict:
    """Log the nudge on the learner's session and deliver it to their session socket (if connected). A socket that
    receives it marks it delivered; one that isn't connected gets it in `ready` on (re)connect (pending_nudges)."""
    s = WorkshopSession.objects.select_related("run").get(pk=session_id)
    sender = learner_out(staff)["name"]
    e = services.event(s, "staff_nudge", text=text, by=staff.id, name=sender)
    async_to_sync(get_channel_layer().group_send)(
        session_group(s.id),
        {"type": "staff.nudge", "id": e.id, "text": text, "from": sender, "at": e.created_at.isoformat()},
    )
    return {"text": text, "from": sender}


def mark_nudge_delivered(event_id, session_id) -> None:
    e = WorkshopEvent.objects.filter(pk=event_id, session_id=session_id, type="staff_nudge").first()
    if e and not (e.data or {}).get("delivered"):
        e.data = {**(e.data or {}), "delivered": True}
        e.save(update_fields=["data"])


def pending_nudges(session_id) -> list[dict]:
    """Staff nudges from the last NUDGE_REPLAY that no socket of the learner received, oldest first: [{id, text, from,
    at}]. Returned once: they are marked delivered here."""
    since = services.now() - NUDGE_REPLAY
    out = []
    for e in WorkshopEvent.objects.filter(
        session_id=session_id, type="staff_nudge", created_at__gte=since
    ).order_by("created_at", "id"):
        d = e.data or {}
        if d.get("delivered"):
            continue
        e.data = {**d, "delivered": True}
        e.save(update_fields=["data"])
        out.append(
            {
                "id": e.id,
                "text": str(d.get("text") or ""),
                "from": str(d.get("name") or ""),
                "at": e.created_at,
            }
        )
    return out


def ack_hand(session_id, staff) -> bool:
    """Clear a raised hand. → whether one was raised."""
    s = WorkshopSession.objects.select_related("run").get(pk=session_id)
    if not _hand_raised(recent_events(s)):
        return False
    services.event(s, "hand_ack", by=staff.id)
    return True
