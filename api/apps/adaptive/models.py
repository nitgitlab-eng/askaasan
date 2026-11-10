"""Adaptive learning: a learner's goal, the course's concept graph, per-concept mastery and each learner's own path.

The author's outline (Section → Subsection) stays the syllabus. Concepts sit under it (which lessons teach what, and
what depends on what); a LearnerPath is one learner's ordered view over that syllabus — lessons, quick skip-checks for
what they already know, and practice to fix what is still shaky. Nothing here ever edits the outline itself."""

from django.conf import settings
from django.db import models


class LearningGoal(models.Model):
    """What the learner wants, understood from a topic: the real-life scenario they picked (or typed and we verified)
    and their constraints. One goal becomes one course."""

    class Status(models.TextChoices):
        SUGGESTED = "suggested"  # scenario cards shown, nothing picked yet
        CHOSEN = "chosen"  # scenario picked/verified, constraints not given yet
        READY = "ready"  # ready to build a course
        USED = "used"  # a course was built from it

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learning_goals"
    )
    topic = models.CharField(max_length=200)
    about = models.CharField(
        max_length=300, blank=True
    )  # the learner's one-line context ("I run a textile shop")
    suggestions = models.JSONField(default=list)  # scenario cards offered
    scenario = models.JSONField(
        default=dict
    )  # {title, deliverable, level, weeks, foundations, custom, verify_notes}
    prior = models.JSONField(default=list)  # things they already know ("excel")
    constraints = models.JSONField(default=dict)  # {no_code, hours_week, deadline_weeks}
    level = models.CharField(max_length=16, default="beginner")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SUGGESTED)
    ai_calls = models.PositiveSmallIntegerField(default=0)  # per-goal AI cap (suggest + verify)
    curriculum = models.OneToOneField(
        "learning.Curriculum", null=True, blank=True, on_delete=models.SET_NULL, related_name="learning_goal"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Concept(models.Model):
    curriculum = models.ForeignKey("learning.Curriculum", on_delete=models.CASCADE, related_name="concepts")
    key = models.SlugField(max_length=60)
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=300, blank=True)
    order = models.PositiveIntegerField(default=0)
    critical = models.BooleanField(
        default=True
    )  # on the way to the learner's goal (must be mastered to finish)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["curriculum", "key"], name="uniq_concept_key")]


class ConceptEdge(models.Model):
    """`prereq` must be understood before `concept`."""

    prereq = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="unlocks")
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="requires")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["prereq", "concept"], name="uniq_concept_edge")]


class ConceptLink(models.Model):
    """Which concepts a lesson teaches (1-3)."""

    subsection = models.ForeignKey(
        "learning.Subsection", on_delete=models.CASCADE, related_name="concept_links"
    )
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="lesson_links")
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [models.UniqueConstraint(fields=["subsection", "concept"], name="uniq_concept_link")]


class ActivityConcept(models.Model):
    """The one concept an activity checks, so an answer moves the right mastery estimate."""

    activity = models.OneToOneField("learning.Activity", on_delete=models.CASCADE, related_name="concept_tag")
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="activity_tags")


class ConceptMastery(models.Model):
    """Bayesian Knowledge Tracing estimate per (learner, concept). Fed by first attempts only."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="concept_mastery"
    )
    concept = models.ForeignKey(Concept, on_delete=models.CASCADE, related_name="mastery")
    p_known = models.FloatField(default=0.2)
    observations = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "concept"], name="uniq_concept_mastery")]


class LearnerPath(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="learner_paths")
    curriculum = models.ForeignKey(
        "learning.Curriculum", on_delete=models.CASCADE, related_name="learner_paths"
    )
    version = models.PositiveIntegerField(default=1)
    reason = models.CharField(max_length=300, blank=True)  # learner-facing: why the path last changed
    replanned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "curriculum"], name="uniq_learner_path")]


class PathItem(models.Model):
    class Kind(models.TextChoices):
        LESSON = "lesson"
        SKIP_CHECK = "skip_check"  # "you seem to know this": a quick fast-track check instead of the lesson
        REMEDIATION = "remediation"  # practice on a lesson whose concept is still shaky
        FINAL = "final"  # the end-of-course check

    class Status(models.TextChoices):
        PENDING = "pending"
        DONE = "done"

    path = models.ForeignKey(LearnerPath, on_delete=models.CASCADE, related_name="items")
    order = models.PositiveIntegerField()
    kind = models.CharField(max_length=12, choices=Kind.choices)
    subsection = models.ForeignKey(
        "learning.Subsection", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    concept = models.ForeignKey(Concept, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING)
    reason = models.CharField(max_length=300, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
