"""Guest links (try a course or role-play without an account) and guest campaigns (AI demo lessons for prospects)."""

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


def _slug():
    return secrets.token_urlsafe(6).replace("_", "x").replace("-", "y").lower()


def hash_token(raw: str) -> str:
    return hashlib.sha256(f"guest:{raw}".encode()).hexdigest()


class GuestLink(models.Model):
    class Target(models.TextChoices):
        COURSE = "course"
        ROLEPLAY = "roleplay"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="guest_links")
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="guest_links"
    )
    label = models.CharField(max_length=120)
    # Stable public address: the author can point the same slug at another course/scenario later.
    slug = models.SlugField(max_length=48, unique=True, default=_slug)
    target_kind = models.CharField(max_length=10, choices=Target.choices, default=Target.COURSE)
    course = models.ForeignKey(
        "learning.Curriculum", null=True, blank=True, on_delete=models.SET_NULL, related_name="guest_links"
    )
    scenario = models.ForeignKey(
        "roleplay.Scenario", null=True, blank=True, on_delete=models.SET_NULL, related_name="guest_links"
    )
    max_uses = models.PositiveIntegerField(null=True, blank=True)  # starts allowed; null = unlimited
    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    collect_email = models.BooleanField(default=False)
    opens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def state(self) -> str:
        """ok | inactive | expired | full | no_target"""
        if not self.active:
            return "inactive"
        if self.expires_at and self.expires_at <= timezone.now():
            return "expired"
        if self.max_uses is not None and self.visitors.count() >= self.max_uses:
            return "full"
        if self.target_kind == self.Target.COURSE and not (self.course_id and self.course.published_at):
            return "no_target"
        if self.target_kind == self.Target.ROLEPLAY and not self.scenario_id:
            return "no_target"
        return "ok"


class GuestVisitor(models.Model):
    """One person who started a guest link. The browser keeps a random token; we store only its hash."""

    link = models.ForeignKey(GuestLink, on_delete=models.CASCADE, related_name="visitors")
    token_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)
    ip_hash = models.CharField(max_length=64, blank=True)
    lessons_done = models.JSONField(default=list, blank=True)  # subsection ids
    magic_version = models.PositiveIntegerField(
        default=0
    )  # bumped when a magic link is used: links are single-use
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    claimed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["link", "email"])]


class GuestAttempt(models.Model):
    visitor = models.ForeignKey(GuestVisitor, on_delete=models.CASCADE, related_name="attempts")
    activity = models.ForeignKey("learning.Activity", on_delete=models.CASCADE, related_name="+")
    answer = models.JSONField()
    score = models.FloatField()
    correct = models.BooleanField()
    feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class GuestRolePlay(models.Model):
    visitor = models.ForeignKey(GuestVisitor, on_delete=models.CASCADE, related_name="roleplays")
    scenario = models.ForeignKey("roleplay.Scenario", on_delete=models.CASCADE, related_name="+")
    turns = models.JSONField(default=list)  # [{role: learner|character, text}]
    status = models.CharField(max_length=12, default="active")  # active | completed
    result = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class GuestAIUsage(models.Model):
    """Daily AI units spent by guests, per link ("link:<id>") and per IP ("ip:<hash>")."""

    key = models.CharField(max_length=80)
    day = models.DateField()
    units = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["key", "day"], name="uniq_guest_ai_usage")]


class GuestCampaign(models.Model):
    org = models.ForeignKey("orgs.Organization", on_delete=models.CASCADE, related_name="guest_campaigns")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    name = models.CharField(max_length=120)
    topic = models.CharField(max_length=200)  # what the demo lessons teach, e.g. "AI tools for everyday work"
    language = models.CharField(max_length=12, default="en")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Prospect(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        GENERATING = "generating"
        READY = "ready"
        FAILED = "failed"
        SENT = "sent"

    campaign = models.ForeignKey(GuestCampaign, on_delete=models.CASCADE, related_name="prospects")
    company = models.CharField(max_length=160)
    email = models.EmailField()
    industry = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    error = models.CharField(max_length=120, blank=True)
    course = models.ForeignKey(
        "learning.Curriculum", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    link = models.ForeignKey(
        GuestLink, null=True, blank=True, on_delete=models.SET_NULL, related_name="prospects"
    )
    subject = models.CharField(
        max_length=160, blank=True
    )  # drafted (for copying); sent mail uses a fixed subject
    body = models.TextField(blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class GuestOptOut(models.Model):
    """Addresses that asked not to receive guest-campaign emails again."""

    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
