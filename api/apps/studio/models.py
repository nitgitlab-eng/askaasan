"""Creator studio: course history (undo/redo + named versions), generation presets, Kili authoring chat, lecture videos."""

from django.conf import settings
from django.db import models


class CourseRevision(models.Model):
    """A full snapshot of an authored course after a change. Undo/redo walks these; pinned ones are named versions."""

    curriculum = models.ForeignKey("learning.Curriculum", on_delete=models.CASCADE, related_name="revisions")
    seq = models.PositiveIntegerField()
    label = models.CharField(max_length=120, blank=True)
    data = models.JSONField()
    pinned = models.BooleanField(default=False)  # named version — never pruned, survives redo truncation
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["seq"]
        constraints = [models.UniqueConstraint(fields=["curriculum", "seq"], name="uniq_course_revision")]


class GenerationPreset(models.Model):
    """A reusable AI pipeline: level, language, activity mix, tone and extra instructions."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="generation_presets"
    )
    name = models.CharField(max_length=80)
    level = models.CharField(max_length=16, blank=True)
    language = models.CharField(max_length=12, blank=True)
    activity_types = models.JSONField(default=list, blank=True)
    tone = models.CharField(max_length=16, default="friendly")  # friendly | formal | playful | exam
    lessons_per_section = models.PositiveSmallIntegerField(default=0)  # 0 = AI decides
    instructions = models.TextField(blank=True, max_length=800)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class AuthoringChat(models.Model):
    """'Build with Kili' conversation for one course; assistant turns carry proposed changes."""

    curriculum = models.OneToOneField(
        "learning.Curriculum", on_delete=models.CASCADE, related_name="authoring_chat"
    )
    messages = models.JSONField(default=list)  # [{role, content, changes?: [...], applied?: [indices]}]
    updated_at = models.DateTimeField(auto_now=True)


def _lecture_path(instance, filename):
    import uuid

    ext = filename.rsplit(".", 1)[-1].lower()[:5] if "." in filename else "bin"
    return f"lectures/{instance.owner_id}/{uuid.uuid4().hex}.{ext}"


class LectureVideo(models.Model):
    class Status(models.TextChoices):
        TRANSCRIBING = "transcribing"
        SEGMENTING = "segmenting"
        READY = "ready"
        FAILED = "failed"

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lectures")
    subsection = models.ForeignKey("learning.Subsection", on_delete=models.CASCADE, related_name="lectures")
    kind = models.CharField(max_length=8)  # youtube | upload
    video_id = models.CharField(max_length=20, blank=True)
    file = models.FileField(upload_to=_lecture_path, blank=True)
    mime = models.CharField(max_length=40, blank=True)
    duration = models.PositiveIntegerField(default=0)  # seconds
    title = models.CharField(max_length=200, blank=True)
    transcript = models.TextField(blank=True)
    segments = models.JSONField(default=list)  # [{start, end, title, summary, checkpoints, accepted}]
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.TRANSCRIBING)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
