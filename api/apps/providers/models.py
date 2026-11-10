from django.conf import settings
from django.db import models
from django.utils import timezone

from . import crypto
from .catalog import CAPABILITIES


class ProviderConfig(models.Model):
    capability = models.CharField(
        max_length=16, unique=True, choices=[(k, v["label"]) for k, v in CAPABILITIES.items()]
    )
    provider = models.CharField(max_length=24)
    model = models.CharField(max_length=80, blank=True)
    voices = models.JSONField(default=dict, blank=True)  # {"en": "...", "ta": "..."}
    encrypted_key = models.TextField(blank=True)
    enabled = models.BooleanField(default=True)
    limits = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)

    def set_key(self, plaintext: str | None):
        self.encrypted_key = crypto.encrypt(plaintext) if plaintext else ""

    def get_key(self) -> str:
        return crypto.decrypt(self.encrypted_key) if self.encrypted_key else ""


class UsageCounter(models.Model):
    """Per-user daily usage, for admin-set voice budgets."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    day = models.DateField(default=timezone.localdate)
    metric = models.CharField(max_length=32)  # stt_seconds | tts_chars
    amount = models.FloatField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "day", "metric"], name="uniq_usage_per_day")]


class LLMUsage(models.Model):
    """One AI call: who/what/which model and how many tokens. Feeds the admin dashboard's AI spend view."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    task = models.CharField(max_length=24)  # tutor | author | grade | suggest | onboarding | vision
    provider = models.CharField(max_length=24)
    model = models.CharField(max_length=80)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cached_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class ModelPrice(models.Model):
    """Admin-entered prices (₹ per 1M tokens). We never guess vendor prices; blank = cost not shown."""

    provider = models.CharField(max_length=24)
    model = models.CharField(max_length=80)
    input_per_m = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    output_per_m = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "model"], name="uniq_model_price")]


class PlatformSettings(models.Model):
    """Platform-wide feature switches set in the admin console (one row, pk=1). Lesson media are off until an admin
    turns them on, so no voice or AI spend happens by surprise."""

    podcast_enabled = models.BooleanField(default=False)
    explainer_enabled = models.BooleanField(default=False)
    listen_enabled = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def load(cls) -> "PlatformSettings":
        return cls.objects.filter(pk=1).first() or cls(pk=1)


class SpeechClip(models.Model):
    """One generated piece of speech, shared by every learner: keyed by sha256(provider|model|voice|lang|text), so the
    same line in the same voice is generated (and charged) once and then served from media storage."""

    key = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=24)
    model = models.CharField(max_length=80, blank=True)
    voice = models.CharField(max_length=80, blank=True)
    lang = models.CharField(max_length=4)
    chars = models.PositiveIntegerField(default=0)
    file = models.CharField(max_length=120)  # storage path, e.g. speech/<key>.mp3
    mime = models.CharField(max_length=40)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
