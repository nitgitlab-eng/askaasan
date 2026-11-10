from django.conf import settings
from django.db import models
from django.utils import timezone


class ReviewCard(models.Model):
    """One spaced-repetition card per (learner, auto-graded activity)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_cards")
    activity = models.ForeignKey("learning.Activity", on_delete=models.CASCADE, related_name="review_cards")
    due = models.DateTimeField(default=timezone.now, db_index=True)
    stability_days = models.FloatField(default=0)  # current interval
    ease = models.FloatField(default=2.5)  # legacy (SM-2)
    difficulty = models.FloatField(default=0)  # FSRS D; 0 = migrate on next review
    reps = models.PositiveIntegerField(default=0)
    lapses = models.PositiveIntegerField(default=0)
    last_reviewed = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "activity"], name="uniq_card")]


class ReviewLog(models.Model):
    card = models.ForeignKey(ReviewCard, on_delete=models.CASCADE, related_name="logs")
    rating = models.PositiveSmallIntegerField()  # 0 again, 2 hard, 3 good
    score = models.FloatField()
    answer = models.JSONField()
    interval_days = models.FloatField()
    confidence = models.PositiveSmallIntegerField(null=True, blank=True)  # 1 guessing · 2 think so · 3 sure
    created_at = models.DateTimeField(auto_now_add=True)


class MasteryRecord(models.Model):
    """Bayesian Knowledge Tracing estimate per (learner, lesson concept)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mastery")
    subsection = models.ForeignKey("learning.Subsection", on_delete=models.CASCADE, related_name="mastery")
    p_known = models.FloatField(default=0.2)
    observations = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "subsection"], name="uniq_mastery")]
