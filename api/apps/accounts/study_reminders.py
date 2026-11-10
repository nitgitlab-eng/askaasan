"""Daily study reminders (Personalize → learning.reminder_times, study_days).

Runs every 15 minutes from Celery beat (or `manage.py send_study_reminders`). When the learner picked a reminder time
it goes exactly then; otherwise at their nudge time (besttime.py: 30 minutes before the time they usually start
studying), rounded down to the 15-minute beat. Idempotent: one reminder per learner per day, skipped if they already
studied today. The email is the daily digest; the bell and push speak in the companion's voice (voice.py), and the
push is left out when a streak-risk or step-up nudge owns today's push (stepup.supersedes_study)."""

from datetime import timedelta

from django.utils import timezone


def due_users(now=None):
    from apps.accounts.models import User
    from apps.accounts.preferences import upgrade

    from .besttime import study_times
    from .cadence import local_now, state_of

    now = local_now(None, now)
    hhmm = now.strftime("%H:%M")
    window = {
        (now - timedelta(minutes=m)).strftime("%H:%M") for m in range(15)
    }  # anything in the last 15 min
    for u in User.objects.filter(is_active=True).select_related("preferences", "profile", "reminder_state"):
        p = upgrade(u.preferences.data)
        if now.weekday() not in p["learning"]["study_days"] or not (study_times(u, p, state_of(u)) & window):
            continue
        yield u, p, hhmm


def send_due(now=None) -> int:
    from apps.accounts.notify import send_optional
    from apps.game.models import Notification
    from apps.game.services import stats_for
    from apps.study.planner import paused_on

    from . import counters, push, voice
    from .digest import build
    from .stepup import supersedes_study
    from .winback import in_progress

    sent = 0
    today = timezone.localdate(now)
    for u, p, _ in due_users(now):
        if Notification.objects.filter(user=u, kind="study_reminder", created_at__date=today).exists():
            continue
        s = stats_for(u)
        if s.last_active == today:
            continue  # already studied today — no nagging
        if paused_on(u.id, today):
            continue  # away mode
        # Atomic claim (durable store): two overlapping runs can both get this far, only one sends.
        if not counters.store().add(f"study-reminder:{u.id}:{today}", 1, 36 * 3600):
            continue
        title, body, html = build(u, p)  # the daily digest: one-tap links to reviews, Today, the next lesson…
        st = in_progress(u)
        msg = voice.pick(u, "study", course=st.subsection.title if st else None)
        Notification.objects.create(
            user=u, kind="study_reminder", title=msg.title, body=msg.body, link="/today"
        )
        send_optional(u, "email_study", title, body, html)
        if not supersedes_study(u, s, today, p):
            push.send(u, "study", msg.title, msg.body, "/today", moment="study", variant=msg.variant)
        sent += 1
    return sent
