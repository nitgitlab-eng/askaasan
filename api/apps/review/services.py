from django.db import transaction
from django.utils import timezone

from .models import MasteryRecord, ReviewCard, ReviewLog
from .scheduling import AUTO_GRADED, CardState, bkt_update, guess_for, rating_for, schedule

PASS = 0.7


def _update_mastery(user, activity, score: float):
    rec, _ = MasteryRecord.objects.select_for_update().get_or_create(
        user=user, subsection_id=activity.subsection_id
    )
    rec.p_known = bkt_update(
        rec.p_known, score >= PASS, guess_for(activity.type, len(activity.payload.get("options", [])))
    )
    rec.observations += 1
    rec.save()


@transaction.atomic
def record_attempt(user, activity, score: float):
    """Called on every lesson/practice attempt: update mastery and make sure the
    activity has a review card (first sight schedules it by performance)."""
    _update_mastery(user, activity, score)
    if activity.type not in AUTO_GRADED:
        return
    card, created = ReviewCard.objects.get_or_create(user=user, activity=activity)
    if created:
        state, due = schedule(CardState(), rating_for(score), timezone.now())
        _apply(card, state, due)


def _apply(card, state, due):
    card.stability_days, card.ease, card.reps, card.lapses = (
        state.stability_days,
        state.ease,
        state.reps,
        state.lapses,
    )
    card.difficulty = state.difficulty
    card.due, card.last_reviewed = due, timezone.now()
    card.save()


@transaction.atomic
def review(card: ReviewCard, score: float, answer: dict, confidence: int | None = None):
    _update_mastery(card.user, card.activity, score)
    rating = rating_for(score)
    if confidence == 1 and rating == 3:  # right, but a guess → see it again sooner
        rating = 2
    elapsed = (timezone.now() - card.last_reviewed).total_seconds() / 86400 if card.last_reviewed else 0.0
    state = CardState(card.stability_days, card.ease, card.reps, card.lapses, card.difficulty, elapsed)
    state, due = schedule(state, rating, timezone.now())
    _apply(card, state, due)
    ReviewLog.objects.create(
        card=card,
        rating=rating,
        score=score,
        answer=answer,
        interval_days=state.stability_days,
        confidence=confidence,
    )
    return rating, due
