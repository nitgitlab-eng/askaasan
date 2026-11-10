from django.conf import settings
from django.db import models


class MediaAsset(models.Model):
    """An image used in lessons/activities. Stored re-encoded (no EXIF/GPS) under an unguessable name."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="media")
    name = models.CharField(max_length=48, unique=True)  # <32 hex>.webp
    kind = models.CharField(max_length=10, default="upload")  # upload | generated
    prompt = models.CharField(max_length=500, blank=True)
    alt = models.CharField(max_length=200, blank=True)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def url(self) -> str:
        return f"/api/media/{self.name}"
