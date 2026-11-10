import secrets

from django.conf import settings
from django.db import models


def _share_token():
    return secrets.token_urlsafe(9)


class Curriculum(models.Model):
    class Status(models.TextChoices):
        GENERATING = "generating"
        READY = "ready"
        FAILED = "failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="curriculums")
    goal = models.CharField(max_length=300)
    level = models.CharField(max_length=16, default="beginner")
    domain = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    source_document = models.ForeignKey(
        "docs.Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="curriculums"
    )
    language = models.CharField(max_length=12, default="en")  # en | ta | tanglish
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    skills = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.GENERATING)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ── Creator Lab ───────────────────────────────────────────────────
    class Kind(models.TextChoices):
        PERSONAL = "personal"  # a learner's own AI course
        AUTHORED = "authored"  # built in the Creator Lab, shareable

    class Visibility(models.TextChoices):
        PRIVATE = "private"  # draft / creator only
        LINK = "link"  # anyone with the share link
        CATALOG = "catalog"  # link + listed in the catalog once approved

    class CatalogStatus(models.TextChoices):
        NONE = "none"
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PERSONAL)
    visibility = models.CharField(max_length=10, choices=Visibility.choices, default=Visibility.PRIVATE)
    catalog_status = models.CharField(
        max_length=10, choices=CatalogStatus.choices, default=CatalogStatus.NONE
    )
    catalog_note = models.CharField(max_length=300, blank=True)  # admin's rejection reason
    share_token = models.CharField(max_length=24, unique=True, default=_share_token)
    cover_emoji = models.CharField(max_length=8, default="📘")
    published_at = models.DateTimeField(null=True, blank=True)
    # Milestone 4 — authoring
    history_pos = models.PositiveIntegerField(
        default=0
    )  # seq of the revision the course currently matches (undo/redo)
    template_scope = models.CharField(max_length=8, blank=True, default="")  # "" | personal | org | global
    template_org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="templates"
    )
    documents = models.ManyToManyField(
        "docs.Document", blank=True, related_name="attached_to"
    )  # grounding material
    authoring = models.JSONField(
        default=dict, blank=True
    )  # {preset: {...}, research: {notes, sources, topic}}

    class Meta:
        ordering = ["-updated_at"]

    @property
    def is_shared(self) -> bool:
        return (
            self.kind == self.Kind.AUTHORED
            and self.visibility != self.Visibility.PRIVATE
            and self.published_at is not None
        )


class Enrollment(models.Model):
    """A learner taking someone else's shared course. Progress stays per-user."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="enrollments")
    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name="enrollments")
    joined_at = models.DateTimeField(auto_now_add=True)
    # Partner cohorts grant access for a window only (both null = permanent). Progress is kept after it ends.
    access_from = models.DateTimeField(null=True, blank=True)
    access_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "curriculum"], name="uniq_enrollment")]


class Section(models.Model):
    curriculum = models.ForeignKey(Curriculum, on_delete=models.CASCADE, related_name="sections")
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    summary = models.TextField(blank=True)
    archived = models.BooleanField(default=False)  # hidden from learners, kept for the author

    class Meta:
        ordering = ["order"]


class Subsection(models.Model):
    class LessonStatus(models.TextChoices):
        EMPTY = "empty"
        GENERATING = "generating"
        READY = "ready"
        FAILED = "failed"

    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name="subsections")
    order = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    objective = models.TextField(blank=True)
    skills = models.JSONField(default=list, blank=True)  # subset of the course skills
    practice_status = models.CharField(max_length=12, default="empty")  # empty|generating|ready|failed
    # When the current lesson/practice job started; lets us recover jobs killed by a restart.
    generating_since = models.DateTimeField(null=True, blank=True)
    lesson_status = models.CharField(max_length=12, choices=LessonStatus.choices, default=LessonStatus.EMPTY)
    explanation_md = models.TextField(blank=True)
    key_points = models.JSONField(default=list, blank=True)
    error = models.CharField(max_length=300, blank=True)
    archived = models.BooleanField(default=False)

    class Meta:
        ordering = ["order"]


class Activity(models.Model):
    TYPES = [
        "quiz",
        "fill_blank",
        "sequencing",
        "categorization",
        "matching",
        "open_input",
        "code",
        "diagram",
        "slides",
        "concept_map",
        "viz",
        "decision_tree",
        "task",
        "map",
        "browser_task",
        "roleplay",
        "video",
        "hotspot",
        "artifact_check",
    ]

    subsection = models.ForeignKey(Subsection, on_delete=models.CASCADE, related_name="activities")
    order = models.PositiveIntegerField()
    type = models.CharField(max_length=24)
    kind = models.CharField(max_length=12, default="lesson")  # lesson | practice
    title = models.CharField(max_length=200)
    payload = models.JSONField()  # safe to send to the learner
    key = models.JSONField()  # answers / rubric — never leaves the server before an attempt
    source = models.JSONField(null=True, blank=True)  # typed authoring form, editable in the Lab

    class Meta:
        ordering = ["order"]


class UserSubsectionState(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started"
        IN_PROGRESS = "in_progress"
        COMPLETED = "completed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    subsection = models.ForeignKey(Subsection, on_delete=models.CASCADE, related_name="states")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.NOT_STARTED)
    score = models.FloatField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "subsection"], name="uniq_user_subsection")]


class ActivityAttempt(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="attempts")
    answer = models.JSONField()
    score = models.FloatField()
    correct = models.BooleanField()
    feedback = models.TextField(blank=True)
    confidence = models.PositiveSmallIntegerField(
        null=True, blank=True
    )  # "how sure?" 1 guessing · 2 think so · 3 sure
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class LessonFeedback(models.Model):
    """One-tap feedback on the recap screen. Feeds recommendations (difficulty), authors and teachers."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    subsection = models.ForeignKey(Subsection, on_delete=models.CASCADE, related_name="feedback")
    rating = models.PositiveSmallIntegerField()  # 1..5
    difficulty = models.CharField(max_length=8, blank=True)  # easy | right | hard
    clarity = models.PositiveSmallIntegerField(null=True, blank=True)  # 1..5
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "subsection"], name="uniq_lesson_feedback")]


def feedback_summary(subsections) -> dict:
    """{subsection_id: {"n", "avg", "hard", "easy"}} for authors / teachers."""
    from django.db.models import Avg, Count, Q

    rows = (
        LessonFeedback.objects.filter(subsection__in=subsections)
        .values("subsection")
        .annotate(
            n=Count("id"),
            avg=Avg("rating"),
            hard=Count("id", filter=Q(difficulty="hard")),
            easy=Count("id", filter=Q(difficulty="easy")),
        )
    )
    return {
        r["subsection"]: {"n": r["n"], "avg": round(r["avg"], 2), "hard": r["hard"], "easy": r["easy"]}
        for r in rows
    }


def next_order(qs) -> int:
    """Position after the last item (0 for an empty list). Not `max or -1`: a max of 0 is falsy."""
    from django.db.models import Max

    m = qs.aggregate(m=Max("order"))["m"]
    return 0 if m is None else m + 1


# ── Learning experience (lx): interactive widgets + Learn-with-Kili tutor ──


class LessonWidget(models.Model):
    """One AI-written interactive widget per lesson. Rendered only in a sandboxed iframe (no same-origin, strict CSP)."""

    class Status(models.TextChoices):
        GENERATING = "generating"
        READY = "ready"
        FAILED = "failed"

    subsection = models.OneToOneField(Subsection, on_delete=models.CASCADE, related_name="widget")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.GENERATING)
    title = models.CharField(max_length=200, blank=True)
    html = models.TextField(blank=True)
    instructions = models.CharField(max_length=500, blank=True)
    checkpoint_question = models.CharField(max_length=300, blank=True)
    answer_key = models.JSONField(
        default=dict, blank=True
    )  # {"kind": "number"|"text", "value": ..., "tolerance": ...} — server only
    error = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TutorSession(models.Model):
    """Chat-paced tutoring of one lesson for one learner: chunks covered, mastery per chunk, the conversation."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    subsection = models.ForeignKey(Subsection, on_delete=models.CASCADE, related_name="tutor_sessions")
    chunks = models.JSONField(default=list)  # [{"title": str, "text": str}]
    current = models.PositiveSmallIntegerField(default=0)  # index of the chunk being taught
    attempts = models.PositiveSmallIntegerField(default=0)  # check answers on the current chunk
    mastery = models.JSONField(default=dict)  # {"0": 0.8, ...}
    question = models.CharField(max_length=600, blank=True)  # the open check question
    messages = models.JSONField(default=list)  # [{"role": "kili"|"me", "text": str}]
    done = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "subsection"], name="uniq_tutor_session")]
