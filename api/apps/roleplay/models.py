from django.conf import settings
from django.db import models


class Scenario(models.Model):
    """A practice situation: the learner plays one role, an AI character the other."""

    class Source(models.TextChoices):
        LIBRARY = "library"  # built-in starter scenarios
        CUSTOM = "custom"  # generated for one learner

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.CUSTOM)
    slug = models.SlugField(max_length=60, blank=True)  # library key
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="scenarios"
    )
    emoji = models.CharField(max_length=8, default="🎭")
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=400)
    learner_role = models.CharField(max_length=300)
    character = models.JSONField()  # {name, persona, goal, style}
    setting = models.CharField(max_length=400)
    objectives = models.JSONField(default=list)  # what the learner should achieve
    competencies = models.JSONField(default=list)  # [{name, description}]
    opening_line = models.CharField(max_length=600)
    difficulty = models.CharField(max_length=12, default="medium")  # easy | medium | hard
    max_turns = models.PositiveSmallIntegerField(default=10)
    # Hard facts (prices, dates, policies) pulled out once by AI for the live fact check; null = not extracted yet.
    facts = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class RolePlaySession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active"
        EVALUATING = "evaluating"
        COMPLETED = "completed"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="roleplays")
    scenario = models.ForeignKey(Scenario, on_delete=models.CASCADE, related_name="sessions")
    # Set when the conversation is a lesson's "roleplay" activity, so the player can send the learner back.
    activity = models.ForeignKey(
        "learning.Activity", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Set when started for a teacher's assignment, so class analytics count each attempt in exactly one org/assignment.
    assignment = models.ForeignKey(
        "orgs.Assignment", null=True, blank=True, on_delete=models.SET_NULL, related_name="roleplay_sessions"
    )
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    language = models.CharField(max_length=12, default="en")
    result = models.JSONField(null=True, blank=True)
    # Kili's private hints ([{text, after_turn}]); never part of the character's transcript.
    hints = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    @property
    def learner_turns(self) -> int:
        return self.turns.filter(role=RolePlayTurn.Role.LEARNER).count()


class RolePlayTurn(models.Model):
    class Role(models.TextChoices):
        LEARNER = "learner"
        CHARACTER = "character"

    session = models.ForeignKey(RolePlaySession, on_delete=models.CASCADE, related_name="turns")
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField()
    # Live coach snapshot after a learner turn: {objectives: [{score, reason}], competencies: [...], checks: [...]}.
    coach = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
