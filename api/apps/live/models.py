from django.conf import settings
from django.db import models


class LiveSession(models.Model):
    """One Live Class. Camera/screen images are never stored; only the spoken/typed transcript is."""

    class Mode(models.TextChoices):
        CAMERA = "camera"
        SCREEN = "screen"
        NONE = "none"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="live_sessions")
    mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.CAMERA)
    topic = models.CharField(max_length=300, blank=True)
    lesson = models.ForeignKey("learning.Subsection", null=True, blank=True, on_delete=models.SET_NULL)
    seconds = models.PositiveIntegerField(default=0)
    frames = models.PositiveIntegerField(default=0)  # snapshots looked at (count only)
    summary = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]


class LiveTurn(models.Model):
    session = models.ForeignKey(LiveSession, on_delete=models.CASCADE, related_name="turns")
    role = models.CharField(max_length=10)  # user | assistant
    text = models.TextField()
    saw_frame = models.BooleanField(default=False)  # this turn was answered while looking at a snapshot
    proactive = models.BooleanField(default=False)  # Kili spoke up on its own after a page change
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
