from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from config.retry import NOTIFY_RETRY

ANNOUNCE_BATCH = 500
ANNOUNCE_GAP_SECONDS = 5  # between batches, so a platform-wide announcement never floods the mail server
RETENTION = timedelta(days=90)


@shared_task
def clean_agent_secrets() -> int:
    """Learner MCP server tokens never outlive 7 days (and are wiped at once when a session is submitted)."""
    from .models import WorkshopAgentServer, WorkshopSession

    old = timezone.now() - timedelta(days=7)
    qs = WorkshopAgentServer.objects.exclude(token_enc="")
    stale = qs.filter(created_at__lt=old) | qs.filter(session__status=WorkshopSession.Status.SUBMITTED)
    return WorkshopAgentServer.objects.filter(pk__in=stale.values("pk")).update(token_enc="")


@shared_task
def clean_old_activity() -> dict:
    """90-day retention for workshop transcripts and events (sessions, scores and certificates stay)."""
    from .models import WorkshopEvent, WorkshopTurn

    cutoff = timezone.now() - RETENTION
    return {
        "events": WorkshopEvent.objects.filter(created_at__lt=cutoff).delete()[0],
        "turns": WorkshopTurn.objects.filter(created_at__lt=cutoff).delete()[0],
    }


def _told_recently(run, title: str) -> set[int]:
    """Users who got this exact workshop notification in the last hour (a retried task must not repeat it)."""
    from apps.game.models import Notification

    from . import public

    return set(
        Notification.objects.filter(
            kind="workshop",
            title=title[:160],
            link=public.run_link(run),
            created_at__gte=timezone.now() - timedelta(hours=1),
        ).values_list("user_id", flat=True)
    )


@shared_task(**NOTIFY_RETRY)
def announce_run(run_id: int, after_id: int = 0) -> int:
    """Tell every active user about a public run, one batch of ANNOUNCE_BATCH users per task (keyset by id); each
    batch queues the next. Re-running a batch skips users who already have this announcement. → users told."""
    from django.contrib.auth import get_user_model

    from apps.game.models import Notification

    from . import public
    from .models import WorkshopRun

    run = WorkshopRun.objects.select_related("workshop").filter(pk=run_id).first()
    if not run or run.status != WorkshopRun.Status.SCHEDULED:
        return 0
    users = list(
        get_user_model()
        .objects.filter(is_active=True, id__gt=after_id)
        .exclude(email__endswith=".invalid")
        .select_related("preferences")
        .order_by("id")[:ANNOUNCE_BATCH]
    )
    if not users:
        return 0
    link = public.run_link(run)
    told = set(
        Notification.objects.filter(user__in=users, kind="workshop_announce", link=link).values_list(
            "user_id", flat=True
        )
    )
    fresh = [u for u in users if u.id not in told]
    w = run.workshop
    title = f"New workshop: {w.title}"[:160]
    price = "Free" if not run.price_paise else f"₹{run.price_paise / 100:,.0f}"
    body = f"{public.when(run)} · {w.duration_minutes} min · {price}. Save your seat."
    Notification.objects.bulk_create(
        [
            Notification(user=u, kind="workshop_announce", title=title, body=body[:300], link=link)
            for u in fresh
        ]
    )
    for u in fresh:
        public.send_email(u, title, body, run)
    if len(users) == ANNOUNCE_BATCH:
        announce_run.apply_async((run_id, users[-1].id), countdown=ANNOUNCE_GAP_SECONDS)
    return len(fresh)


@shared_task(bind=True, **NOTIFY_RETRY)
def notify_enrolled(self, run_id: int, what: str) -> int:
    """`what` = "moved" (new start time) or "cancelled". In-app always, email per preferences. A retry after an
    outage skips learners the failed attempt already told."""
    from . import public
    from .models import WorkshopEnrollment, WorkshopRun

    run = WorkshopRun.objects.select_related("workshop").filter(pk=run_id).first()
    if not run:
        return 0
    w = run.workshop
    if what == "cancelled":
        title = f"Cancelled: {w.title}"
        body = f"The workshop on {public.when(run)} has been cancelled."
    else:
        title = f"New time for {w.title}"
        body = f"The workshop now starts {public.when(run)}."
    told = _told_recently(run, title) if self.request.retries else set()
    n = 0
    for e in (
        WorkshopEnrollment.objects.filter(run=run)
        .exclude(user_id__in=told)
        .select_related("user__preferences")
        .iterator(chunk_size=500)
    ):
        extra = " Your payment will be refunded in full." if what == "cancelled" and e.order_id else ""
        public.tell(e.user, title[:160], body + extra, run)
        n += 1
    return n


@shared_task(bind=True, **NOTIFY_RETRY)
def notify_org_run(self, run_id: int, user_ids: list[int]) -> int:
    """Institution runs: tell the auto-enrolled learners (in-app always, email per preferences). A retry after an
    outage skips learners the failed attempt already told."""
    from . import public
    from .models import WorkshopEnrollment, WorkshopRun

    run = (
        WorkshopRun.objects.select_related("workshop", "org")
        .filter(pk=run_id, audience=WorkshopRun.Audience.ORG)
        .exclude(status=WorkshopRun.Status.CANCELLED)
        .first()
    )
    if not run:
        return 0
    w = run.workshop
    by = run.org.display_name or run.org.name
    title = f"New workshop for your class: {w.title}"[:160]
    body = f"{by} enrolled you. {public.when(run)} · {w.duration_minutes} min · free."
    told = _told_recently(run, title) if self.request.retries else set()
    n = 0
    for e in (
        WorkshopEnrollment.objects.filter(run=run, user_id__in=user_ids)
        .exclude(user_id__in=told)
        .select_related("user__preferences")
        .iterator(chunk_size=500)
    ):
        public.tell(e.user, title, body, run)
        n += 1
    return n


@shared_task(**NOTIFY_RETRY)
def send_reminders() -> dict:
    """Every 5 min: a 24 h and a 15 min reminder to each enrolled learner, each sent once (a conditional update claims
    the flag, so overlapping runs of this task can't double-send). Joining late? The 15 min one covers both."""
    from . import public, services
    from .models import WorkshopEnrollment, WorkshopRun

    now = services.now()
    sent = {"24h": 0, "15m": 0}
    live = (WorkshopRun.Status.SCHEDULED, WorkshopRun.Status.LIVE)
    base = WorkshopEnrollment.objects.filter(
        run__status__in=live, run__audience__in=(WorkshopRun.Audience.PUBLIC, WorkshopRun.Audience.ORG)
    ).select_related("run__workshop", "user__preferences")
    soon = base.filter(
        reminded_15m=False,
        run__starts_at__lte=now + timedelta(minutes=15),
        run__starts_at__gt=now - timedelta(minutes=60),
    )
    for e in soon:
        run = e.run
        if now > run.join_window()[1]:
            continue
        if WorkshopEnrollment.objects.filter(pk=e.pk, reminded_15m=False).update(
            reminded_15m=True, reminded_24h=True
        ):
            public.tell(
                e.user,
                f"Starting soon: {run.workshop.title}"[:160],
                f"Starts {public.when(run)}. The lobby is open: get your prerequisites ready.",
                run,
            )
            sent["15m"] += 1
    day = base.filter(
        reminded_24h=False,
        run__starts_at__lte=now + timedelta(hours=24),
        run__starts_at__gt=now + timedelta(minutes=15),
    )
    for e in day:
        if WorkshopEnrollment.objects.filter(pk=e.pk, reminded_24h=False).update(reminded_24h=True):
            run = e.run
            public.tell(
                e.user,
                f"Reminder: {run.workshop.title}"[:160],
                f"Your workshop starts {public.when(run)}.",
                run,
            )
            sent["24h"] += 1
    return sent


@shared_task
def sync_run_status() -> dict:
    """Saves what effective_status() already computes on read: scheduled → live → ended."""
    from . import services
    from .models import WorkshopRun

    now = services.now()
    out = {"live": 0, "ended": 0}
    rows = (
        WorkshopRun.objects.filter(
            status__in=(WorkshopRun.Status.SCHEDULED, WorkshopRun.Status.LIVE), starts_at__lte=now
        )
        .exclude(audience=WorkshopRun.Audience.TEST)
        .select_related("workshop")
    )
    for run in rows:
        st = run.effective_status(now)
        if st != run.status:
            # Conditional: a cancel that lands meanwhile wins.
            n = WorkshopRun.objects.filter(pk=run.pk, status=run.status).update(status=st)
            out[st] += n
    return out
