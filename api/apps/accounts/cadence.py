"""How often reminder pushes may go out, and backing off when they are ignored.

Reminder kinds (study, streak, reviews, winback) are gated here; teacher, workshop, plan and test pushes never are.
- Ignored = reminder pushes (not the back-off notice) still unopened that were sent after the learner's last activity,
  last open or last manual resume. IGNORED_TO_ALTERNATE of them → `alternate` (reminders only every other day);
  IGNORED_TO_PAUSE → `paused` (only win-back). Evaluated nightly (`evaluate_all`).
- On first entering `paused`, one `backoff_notice` push + bell explains it (daytime only, from the 15-minute run).
- Any open (the service worker's ping, or opening the app within OPEN_WINDOW of a push), any activity
  (`game.services.award`) or the Resume button puts the learner back to `normal`.
- At most DAILY_CAP reminder pushes a day, whatever the state.

There is no per-user time zone yet (everything is Asia/Kolkata): every local-time computation goes through
`local_now(user, now)` so one can be added in one place."""

import logging
import re
from datetime import timedelta

from django.utils import timezone

log = logging.getLogger(__name__)

REMINDER_KINDS = frozenset({"study", "streak", "reviews", "winback"})
IGNORED_TO_ALTERNATE = 5
IGNORED_TO_PAUSE = 8
OPEN_WINDOW = timedelta(hours=6)  # opening the app this soon after a push counts as opening it
OPEN_MAX_AGE = timedelta(days=7)  # the service worker's ping is accepted for pushes this recent
DAILY_CAP = 2  # reminder pushes per learner per local day
RETENTION = timedelta(days=90)
QUIET_START, QUIET_END = 22 * 60, 8 * 60  # system-timed pushes never 22:00-08:00
NOTICE = "backoff_notice"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,32}$")


def local_now(user, now=None):
    """The learner's local time. One place to add a per-user time zone later."""
    return timezone.localtime(now or timezone.now())


def local_minute(user, now=None) -> int:
    t = local_now(user, now)
    return t.hour * 60 + t.minute


def daytime(minute: int) -> bool:
    return QUIET_END <= minute < QUIET_START


def _day_start(user, now):
    return local_now(user, now).replace(hour=0, minute=0, second=0, microsecond=0)


def state_of(user):
    """The learner's ReminderState for reading (an unsaved default when there is none yet)."""
    from .models import ReminderState

    try:
        return user.reminder_state
    except ReminderState.DoesNotExist:
        return ReminderState(user=user)


def state_for(user):
    from .models import ReminderState

    return ReminderState.objects.get_or_create(user=user)[0]


# ── The gate push.send() calls ──


def allowed(user, kind: str, moment: str = "", now=None) -> bool:
    if kind not in REMINDER_KINDS or moment == NOTICE:
        return True
    from .models import PushLog, ReminderState

    now = now or timezone.now()
    st = ReminderState.objects.filter(user=user).only("backoff", "backoff_since").first()
    state = st.backoff if st else "normal"
    if state == "paused" and kind != "winback":
        return False
    if state == "alternate" and st.backoff_since:
        days = (local_now(user, now).date() - local_now(user, st.backoff_since).date()).days
        if days % 2:
            return False
    sent_today = (
        PushLog.objects.filter(user=user, kind__in=REMINDER_KINDS, sent_at__gte=_day_start(user, now))
        .exclude(moment=NOTICE)
        .count()
    )
    return sent_today < DAILY_CAP


def log_push(user, kind: str, moment: str = "", variant: str = "", now=None):
    import secrets

    from .models import PushLog

    return PushLog.objects.create(
        user=user,
        token=secrets.token_urlsafe(16),
        kind=kind[:16],
        moment=(moment or "")[:24],
        variant=(variant or "")[:40],
        sent_at=now or timezone.now(),
    )


# ── Back to normal ──


def resume(user_id: int, now=None, manual: bool = False) -> bool:
    """Back to normal reminders. → True if the learner was backed off."""
    from .models import ReminderState

    now = now or timezone.now()
    changed = (
        ReminderState.objects.filter(user_id=user_id)
        .exclude(backoff="normal")
        .update(backoff="normal", backoff_since=None, notice_sent_at=None)
    )
    if manual:
        ReminderState.objects.update_or_create(user_id=user_id, defaults={"reset_at": now})
    return bool(changed)


def on_activity(user_id: int) -> None:
    """Called from game.services.award: one indexed UPDATE that only touches backed-off rows."""
    from .models import ReminderState

    ReminderState.objects.filter(user_id=user_id).exclude(backoff="normal").update(
        backoff="normal", backoff_since=None, notice_sent_at=None
    )


def mark_opened(token, now=None) -> bool:
    """The service worker reported a tap on push `token`. → True if a recent, unopened push matched."""
    from .models import PushLog

    if not isinstance(token, str) or not TOKEN_RE.match(token):
        return False
    now = now or timezone.now()
    row = (
        PushLog.objects.filter(token=token, opened_at__isnull=True, sent_at__gte=now - OPEN_MAX_AGE)
        .only("pk", "user_id")
        .first()
    )
    if not row:
        return False
    if not PushLog.objects.filter(pk=row.pk, opened_at__isnull=True).update(opened_at=now, opened_via="push"):
        return False
    resume(row.user_id, now)
    return True


def mark_app_visit(user, now=None) -> int:
    """Opening the app soon after a push counts as opening it (the learner may have ignored the banner itself)."""
    from .models import PushLog

    now = now or timezone.now()
    n = PushLog.objects.filter(user=user, sent_at__gte=now - OPEN_WINDOW, opened_at__isnull=True).update(
        opened_at=now, opened_via="app"
    )
    if n:
        resume(user.pk, now)
    return n


# ── Nightly evaluation ──


def ignored_count(user_id: int) -> int:
    from django.db.models import Max

    from apps.game.models import XPEvent

    from .models import PushLog, ReminderState

    marks = [
        XPEvent.objects.filter(user_id=user_id).aggregate(m=Max("created_at"))["m"],
        PushLog.objects.filter(user_id=user_id, opened_at__isnull=False).aggregate(m=Max("opened_at"))["m"],
        ReminderState.objects.filter(user_id=user_id).values_list("reset_at", flat=True).first(),
    ]
    since = max((m for m in marks if m), default=None)
    q = PushLog.objects.filter(user_id=user_id, kind__in=REMINDER_KINDS, opened_at__isnull=True).exclude(
        moment=NOTICE
    )
    if since:
        q = q.filter(sent_at__gt=since)
    return q.count()


def target_state(ignored: int) -> str:
    if ignored >= IGNORED_TO_PAUSE:
        return "paused"
    if ignored >= IGNORED_TO_ALTERNATE:
        return "alternate"
    return "normal"


RANK = {"normal": 0, "alternate": 1, "paused": 2}


def evaluate(user_id: int, now=None) -> str:
    """Step the learner down (never up: opens, activity and Resume do that) by how many pushes went unopened."""
    from .models import ReminderState

    now = now or timezone.now()
    want = target_state(ignored_count(user_id))
    st = ReminderState.objects.get_or_create(user_id=user_id)[0]
    if RANK[want] > RANK[st.backoff]:
        ReminderState.objects.filter(pk=st.pk).update(backoff=want, backoff_since=now)
        return want
    return st.backoff


def evaluate_all(now=None) -> dict:
    from .models import PushLog

    now = now or timezone.now()
    out = {"normal": 0, "alternate": 0, "paused": 0}
    users = (
        PushLog.objects.filter(
            kind__in=REMINDER_KINDS, opened_at__isnull=True, sent_at__gte=now - timedelta(days=30)
        )
        .values_list("user_id", flat=True)
        .distinct()
    )
    for uid in list(users):
        try:
            out[evaluate(uid, now)] += 1
        except Exception:
            log.exception("cadence: evaluating user %s failed", uid)
    return out


def prune(now=None) -> int:
    from .models import PushLog

    now = now or timezone.now()
    return PushLog.objects.filter(sent_at__lt=now - RETENTION).delete()[0]


# ── The one notice ──


def send_notices(now=None) -> int:
    """Tell newly paused learners once, in the daytime, that reminders paused and how to bring them back."""
    from apps.game.services import notify

    from . import push, voice
    from .models import ReminderState

    now = now or timezone.now()
    sent = 0
    rows = ReminderState.objects.filter(backoff="paused", notice_sent_at__isnull=True).select_related(
        "user__profile", "user__preferences"
    )
    for st in rows:
        u = st.user
        try:
            if not u.is_active or not daytime(local_minute(u, now)):
                continue
            # Claim first, so a rerun or a retry never tells them twice.
            if not ReminderState.objects.filter(pk=st.pk, notice_sent_at__isnull=True).update(
                notice_sent_at=now
            ):
                continue
            msg = voice.pick(u, NOTICE)
            notify(u, "reminders", msg.title, msg.body, "/account#push")
            push.send(u, "study", msg.title, msg.body, "/account#push", moment=NOTICE, variant=msg.variant)
            sent += 1
        except Exception:
            log.exception("cadence: back-off notice for user %s failed", u.id)
    return sent


def status(user) -> dict:
    from . import besttime

    st = state_of(user)
    best = st.best_minute
    return {
        "state": st.backoff,
        "since": st.backoff_since.isoformat() if st.backoff_since and st.backoff != "normal" else None,
        "learned_time": besttime.hhmm(best) if best is not None else None,
        "time_chosen": st.time_chosen,
    }
