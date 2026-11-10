"""Help centre articles (admin-editable, English + Tamil) and 'Report a problem' tickets."""

from django.conf import settings
from django.db import models


class HelpArticle(models.Model):
    slug = models.SlugField(max_length=80, unique=True)
    category = models.CharField(max_length=24, default="start")  # start | learn | teach | account | faq
    title = models.CharField(max_length=160)
    title_ta = models.CharField(max_length=200, blank=True)
    body_md = models.TextField()
    body_ta_md = models.TextField(blank=True)
    order = models.PositiveSmallIntegerField(default=0)
    published = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "order", "title"]


class ProblemReport(models.Model):
    class Status(models.TextChoices):
        NEW = "new"
        TRIAGING = "triaging"
        FIXED = "fixed"
        CLOSED = "closed"

    CATEGORIES = ("bug", "content", "answer", "billing", "account", "idea", "other")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="problem_reports",
    )
    email = models.EmailField(blank=True)  # where to reply (defaults to the account email)
    category = models.CharField(max_length=12, default="bug")
    text = models.TextField(max_length=4000)
    page = models.CharField(max_length=300, blank=True)
    ref = models.CharField(max_length=60, blank=True)  # e.g. "answer:message:123" from 👎 → Report
    screenshot = models.CharField(max_length=300, blank=True)  # our own media URL
    browser = models.CharField(max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.NEW)
    reply = models.TextField(blank=True)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
