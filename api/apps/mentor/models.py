from django.conf import settings
from django.db import models


class Conversation(models.Model):
    class Kind(models.TextChoices):
        ASSISTANT = "assistant"
        LESSON = "lesson"
        ONBOARDING = "onboarding"
        DOCUMENT = "document"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.ASSISTANT)
    title = models.CharField(max_length=160, blank=True)
    document = models.ForeignKey(
        "docs.Document", null=True, blank=True, on_delete=models.CASCADE, related_name="conversations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user"
        ASSISTANT = "assistant"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=10, choices=Role.choices)
    content = models.TextField()
    stop_reason = models.CharField(max_length=24, blank=True)
    model = models.CharField(max_length=64, blank=True)
    usage = models.JSONField(default=dict, blank=True)
    citations = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]


class AnswerFeedback(models.Model):
    """👍/👎 on any AI answer: mentor & notes chat (message), Live Class turn (live), role-play reply (roleplay)."""

    KINDS = ("message", "live", "roleplay")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=10)
    object_id = models.PositiveIntegerField()
    rating = models.SmallIntegerField()  # +1 / -1
    reason = models.CharField(max_length=24, blank=True)  # wrong | unclear | too_long | unsafe | other
    comment = models.CharField(max_length=500, blank=True)
    model = models.CharField(max_length=64, blank=True)
    excerpt = models.CharField(
        max_length=300, blank=True
    )  # start of the rated answer, for the admin review list
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "kind", "object_id"], name="uniq_answer_feedback")
        ]
