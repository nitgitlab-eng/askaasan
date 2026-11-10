"""HR onboarding journeys: a day-by-day plan for new joiners (lessons, role-plays, shadowing, documents, HR notes)."""

from django.conf import settings
from django.db import models


class Journey(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="journeys")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    length_days = models.PositiveSmallIntegerField(default=30)
    phases = models.JSONField(
        default=list, blank=True
    )  # [{"title", "start_day", "end_day"}], validated in services.clean_phases
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class JourneyItem(models.Model):
    class Kind(models.TextChoices):
        LESSON = "lesson"  # a course (or one lesson of it): completes through normal lesson completion
        SCENARIO = "scenario"  # a role-play practice
        SHADOW = "shadow"  # shadow a colleague (free-text name / role)
        DOCUMENT = "document"  # an org knowledge-base document the learner may read
        NOTE = "note"  # HR notes / tips

    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name="items")
    day = models.PositiveSmallIntegerField()
    order = models.PositiveSmallIntegerField(default=0)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=160, blank=True)
    notes = models.TextField(max_length=1000, blank=True)
    curriculum = models.ForeignKey(
        "learning.Curriculum", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    subsection = models.ForeignKey(
        "learning.Subsection", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    scenario = models.ForeignKey(
        "roleplay.Scenario", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    document = models.ForeignKey(
        "orgs.OrgDocument", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    colleague_name = models.CharField(max_length=80, blank=True)
    colleague_role = models.CharField(max_length=80, blank=True)

    class Meta:
        ordering = ["day", "order", "id"]


class JourneyAssignment(models.Model):
    """One new joiner on one journey, starting on `start_date` (Day 1)."""

    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name="assignments")
    membership = models.ForeignKey("orgs.Membership", on_delete=models.CASCADE, related_name="journeys")
    start_date = models.DateField()
    group = models.ForeignKey(
        "orgs.Group", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # assigned via a class
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["journey", "membership"], name="uniq_journey_member")]
        ordering = ["-start_date", "id"]


class JourneyTick(models.Model):
    """A learner ticked off a non-lesson item (lesson items complete through lesson progress)."""

    assignment = models.ForeignKey(JourneyAssignment, on_delete=models.CASCADE, related_name="ticks")
    item = models.ForeignKey(JourneyItem, on_delete=models.CASCADE, related_name="ticks")
    done_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["assignment", "item"], name="uniq_journey_tick")]
