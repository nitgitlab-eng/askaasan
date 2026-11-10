"""Streak-at-risk and reviews-due pushes (Celery beat `evening-checks`, every 15 minutes).

Each learner with a push device is nudged from their own nudge time (besttime.nudge_minute: 30 minutes before the
time they usually start studying, or before their reminder time; kept within 08:00-21:30) and never 22:00-08:00:
"your streak is at risk" and "reviews are piling up", in the companion's voice (voice.py). Each at most once a day per
learner (the in-app Notification it creates is the marker), skipped on away-mode days."""

from datetime import timedelta

from django.utils import timezone

REVIEWS_MIN = 5


def run(now=None) -> dict:
    from apps.game.models import Notification, PlayerStats
    from apps.review.models import ReviewCard
    from apps.study.planner import paused_on

    from . import besttime, cadence, push, voice
    from .models import PushSubscription, User
    from .preferences import upgrade

    out = {"streak": 0, "reviews": 0}
    now = now or timezone.now()
    if not push.enabled():
        return out
    users = (
        User.objects.filter(is_active=True, pk__in=PushSubscription.objects.values("user"))
        .exclude(age_band="minor")  # no behavioural nudges for under-18s (DPDP Act s.9)
        .select_related("profile", "preferences", "reminder_state")
    )
    for u in users:
        minute = cadence.local_minute(u, now)
        prefs = upgrade(u.preferences.data)
        if not cadence.daytime(minute) or minute < besttime.nudge_minute(u, prefs, cadence.state_of(u)):
            continue
        today = cadence.local_now(u, now).date()
        if paused_on(u.id, today):
            continue
        told = set(
            Notification.objects.filter(
                user=u, kind__in=("streak_risk", "review_due"), created_at__date=today
            ).values_list("kind", flat=True)
        )
        s = PlayerStats.objects.filter(user=u).first()
        if "streak_risk" not in told and s and s.streak >= 2 and s.last_active == today - timedelta(days=1):
            msg = voice.pick(u, "streak_risk", n=s.streak)
            Notification.objects.create(
                user=u, kind="streak_risk", title=msg.title, body=msg.body, link="/today"
            )
            push.send(u, "streak", msg.title, msg.body, "/today", moment="streak_risk", variant=msg.variant)
            out["streak"] += 1
        if "review_due" not in told:
            due = ReviewCard.objects.filter(user=u, due__lte=now).count()
            if due >= REVIEWS_MIN:
                msg = voice.pick(u, "reviews", n=due)
                Notification.objects.create(
                    user=u, kind="review_due", title=msg.title, body=msg.body, link="/review"
                )
                push.send(u, "reviews", msg.title, msg.body, "/review", moment="reviews", variant=msg.variant)
                out["reviews"] += 1
    return out
