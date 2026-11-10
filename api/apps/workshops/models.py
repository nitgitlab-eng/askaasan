"""AI-run workshops: a template (Workshop), one scheduled offering of it (WorkshopRun), the learners signed up
(WorkshopEnrollment) and each learner's own learner-paced attempt (WorkshopSession) with its transcript and events.

Screenshots shared for help are never stored: an event keeps only the AI's short text summary of them."""

from datetime import timedelta

from django.conf import settings
from django.db import models

PROCTORING = [("off", "Off"), ("activity", "Activity"), ("strict", "Strict")]


class Workshop(models.Model):
    """A template. Agenda stage: {key, kind, title, minutes, goal, concepts[], material_md, task, steps[],
    questions[]}; kind is teach | check | diy | build | agent_build | assessment. `final` holds the MCQs (with their
    keys, which never leave the server) and the practical's prompt and rubric."""

    class Level(models.TextChoices):
        BEGINNER = "beginner"
        INTERMEDIATE = "intermediate"
        ADVANCED = "advanced"

    slug = models.SlugField(max_length=60, unique=True)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=400, blank=True)
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.BEGINNER)
    duration_minutes = models.PositiveSmallIntegerField(default=90)  # planned time (10-120), a guide only
    grace_minutes = models.PositiveSmallIntegerField(default=30)  # a message only; never cuts the learner off
    prerequisites = models.JSONField(default=list, blank=True)  # [{key, label, how_to_md, check_hint}]
    agenda = models.JSONField(default=list, blank=True)
    final = models.JSONField(default=dict, blank=True)
    pass_mark = models.FloatField(default=0.6)
    language = models.CharField(max_length=12, default="en")
    proctoring = models.CharField(max_length=8, choices=PROCTORING, default="off")
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["duration_minutes", "title"]

    def __str__(self):
        return self.title


class WorkshopRun(models.Model):
    """One offering with a start time. M1: public runs and staff test runs; org runs, paid checkout and
    announcements arrive in later milestones (the fields are here already)."""

    class Audience(models.TextChoices):
        PUBLIC = "public"
        ORG = "org"
        TEST = "test"  # a staff member's private try-out of a template

    class Status(models.TextChoices):
        DRAFT = "draft"
        SCHEDULED = "scheduled"
        LIVE = "live"
        ENDED = "ended"
        CANCELLED = "cancelled"

    workshop = models.ForeignKey(Workshop, on_delete=models.CASCADE, related_name="runs")
    audience = models.CharField(max_length=8, choices=Audience.choices, default=Audience.PUBLIC)
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="workshop_runs"
    )
    groups = models.ManyToManyField("orgs.Group", blank=True, related_name="workshop_runs")
    cohorts = models.ManyToManyField("orgs.Cohort", blank=True, related_name="workshop_runs")
    starts_at = models.DateTimeField()
    late_join_minutes = models.PositiveSmallIntegerField(default=15)
    lobby_opens_minutes = models.PositiveSmallIntegerField(default=15)
    proctoring = models.CharField(max_length=8, choices=PROCTORING, blank=True)  # "" = the template's setting
    capacity = models.PositiveIntegerField(null=True, blank=True)
    price_paise = models.PositiveIntegerField(default=0)  # 0 = free
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    announced_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at"]

    # A run counts as ended this long after its planned time and grace (sessions in progress always carry on).
    END_AFTER = timedelta(hours=12)

    @property
    def effective_proctoring(self) -> str:
        return self.proctoring or self.workshop.proctoring

    def join_window(self):
        """The lobby opens (and a session can be created for prep) → late join closes."""
        return (
            self.starts_at - timedelta(minutes=self.lobby_opens_minutes),
            self.starts_at + timedelta(minutes=self.late_join_minutes),
        )

    @property
    def ends_at(self):
        w = self.workshop
        return self.starts_at + timedelta(minutes=w.duration_minutes + w.grace_minutes) + self.END_AFTER

    def effective_status(self, at) -> str:
        """scheduled → live at starts_at → ended at ends_at, whether or not the beat task has saved it yet. Draft,
        cancelled and staff test runs keep their stored status."""
        st = self.status
        if self.audience == self.Audience.TEST or st not in (self.Status.SCHEDULED, self.Status.LIVE):
            return st
        if at >= self.ends_at:
            return self.Status.ENDED
        return self.Status.LIVE if at >= self.starts_at else self.Status.SCHEDULED


class WorkshopEnrollment(models.Model):
    run = models.ForeignKey(WorkshopRun, on_delete=models.CASCADE, related_name="enrollments")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workshop_enrollments"
    )
    order = models.ForeignKey(
        "billing.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    reminded_24h = models.BooleanField(default=False)
    reminded_15m = models.BooleanField(default=False)
    refund_due = models.BooleanField(default=False)  # a paid seat on a cancelled run: staff refund it

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "user"], name="uniq_workshop_enrollment")]


class WorkshopSession(models.Model):
    """One learner's attempt. `in_grace` / `overtime` are labels only: nothing is ever cut off or auto-submitted."""

    class Status(models.TextChoices):
        PREREQ = "prereq"
        ACTIVE = "active"
        IN_GRACE = "in_grace"
        OVERTIME = "overtime"
        SUBMITTED = "submitted"

    enrollment = models.OneToOneField(WorkshopEnrollment, on_delete=models.CASCADE, related_name="session")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workshop_sessions"
    )
    run = models.ForeignKey(WorkshopRun, on_delete=models.CASCADE, related_name="sessions")
    # Prerequisites: key → ticked_at; ready_at once every one is ticked.
    prereqs_done = models.JSONField(default=dict, blank=True)
    ready_at = models.DateTimeField(null=True, blank=True)
    proctor_notice_at = models.DateTimeField(null=True, blank=True)
    # Timing
    started_at = models.DateTimeField(null=True, blank=True)
    planned_end = models.DateTimeField(null=True, blank=True)
    grace_end = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREREQ)
    grace_announced = models.BooleanField(default=False)
    # Progress: stage_state = {"<stage index>": {"cursor", "items": [...]}, "_lang", "_cap_from", "_att"}
    stage_index = models.PositiveSmallIntegerField(default=0)
    stage_state = models.JSONField(default=dict, blank=True)
    scores = models.JSONField(default=dict, blank=True)  # stage key → 0..1
    final_score = models.FloatField(null=True, blank=True)
    final_attempts = models.PositiveSmallIntegerField(default=0)
    passed = models.BooleanField(default=False)
    certificate = models.ForeignKey(
        "credentials.Certificate", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    agent = models.JSONField(default=dict, blank=True)  # the learner's agent config (agent builder, M2)
    ai_units = models.PositiveIntegerField(default=0)  # spent against WORKSHOP_SESSION_AI_UNITS
    # Attention aggregates (only ever filled when proctoring is on, and never during DIY stages)
    focus_losses = models.PositiveIntegerField(default=0)
    hidden_seconds = models.PositiveIntegerField(default=0)
    idle_seconds = models.PositiveIntegerField(default=0)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    attention_score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class WorkshopTurn(models.Model):
    session = models.ForeignKey(WorkshopSession, on_delete=models.CASCADE, related_name="turns")
    role = models.CharField(max_length=10)  # user | assistant
    text = models.TextField()
    stage = models.PositiveSmallIntegerField(default=0)
    # A host reply interrupted before it finished: kept in the learner's transcript, but it never counts as an
    # explanation and never goes back into the model's context.
    cancelled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class WorkshopEvent(models.Model):
    """stage_start, concept_done, concept_skipped, answer, diy_step_done, step_skipped, help_screenshot, help_error,
    tab_hidden, tab_visible, blur, focus, idle, active, fs_exit, raise_hand, staff_nudge (+ delivered), ai_turn, final_attempt,
    build_graded. `data` stays small and never holds an image or pasted logs."""

    session = models.ForeignKey(WorkshopSession, on_delete=models.CASCADE, related_name="events")
    type = models.CharField(max_length=24)
    stage = models.PositiveSmallIntegerField(default=0)
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["session", "type"])]


class WorkshopAgentServer(models.Model):
    """A learner's own remote MCP server (Streamable HTTP) connected to their workshop agent.

    `token_enc` holds the learner's bearer token / API-key header encrypted with apps.providers.crypto; it is never
    returned to the browser, logged, sent to a model or exported, and is wiped when the session is submitted and by
    the 7-day cleanup (tasks.clean_agent_secrets). `tools` keeps the sanitised tool list: [{name, description,
    input_schema}]."""

    session = models.ForeignKey(WorkshopSession, on_delete=models.CASCADE, related_name="agent_servers")
    label = models.CharField(max_length=40, blank=True)
    url = models.CharField(max_length=500)
    token_enc = models.TextField(blank=True)
    status = models.CharField(max_length=12, default="connected")  # connected | error
    error = models.CharField(max_length=24, blank=True)
    tools = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    refreshed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
