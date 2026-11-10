import secrets

from django.conf import settings
from django.db import models


def _code():
    return secrets.token_urlsafe(18)  # 24 URL-safe chars, 144 bits: unguessable


class Certificate(models.Model):
    """A verifiable certificate. Public verification shows only: learner display name, title, course author, issuer (+ type), date."""

    class Kind(models.TextChoices):
        COURSE = "course"
        SCENARIO = "scenario"
        TEST = "test"
        WORKSHOP = "workshop"  # always issued by Aasan

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="certificates")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=200)  # snapshot of the course / scenario / test title
    learner_name = models.CharField(max_length=120)  # display name at issue time (never the email)
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # null = Aasan
    issuer_name = models.CharField(max_length=120)
    author_name = models.CharField(max_length=120, blank=True)  # courses: who made it ("Course by …")
    # Snapshots, so a deleted organisation's certificate can never turn into an "Issued by Aasan" one
    issuer_type = models.CharField(max_length=12, default="aasan")  # aasan | organisation
    issuer_slug = models.CharField(max_length=80, blank=True)
    curriculum = models.ForeignKey(
        "learning.Curriculum", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    scenario = models.ForeignKey(
        "roleplay.Scenario", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    survey = models.ForeignKey(
        "orgs.Survey", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    workshop_run = models.ForeignKey(
        "workshops.WorkshopRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    detail = models.JSONField(default=dict, blank=True)  # e.g. {"pct": 85} for a passed test
    code = models.CharField(max_length=40, unique=True, default=_code)
    dedupe = models.CharField(
        max_length=80, unique=True
    )  # one certificate per learner + kind + issuer + item
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    hidden = models.BooleanField(default=False)  # owner hid the public page (can show again)
    revoked_at = models.DateTimeField(null=True, blank=True)  # permanent

    class Meta:
        ordering = ["-issued_at"]


class CertificateTemplate(models.Model):
    """How certificates look. Platform-wide (org empty) or an organisation's own; optionally only for one kind and/or
    one language. The most specific active match wins (see templates.resolve). Images are our own media URLs only."""

    class Layout(models.TextChoices):
        CLASSIC = "classic"
        MODERN = "modern"
        MINIMAL = "minimal"

    org = models.ForeignKey(
        "orgs.Organization",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="certificate_templates",
    )
    kind = models.CharField(max_length=10, blank=True)  # "" = every kind
    language = models.CharField(max_length=8, blank=True)  # "" = every language
    layout = models.CharField(max_length=8, choices=Layout.choices, default=Layout.CLASSIC)
    colors = models.JSONField(default=dict, blank=True)  # {ink, accent, gold, paper}: #rrggbb
    headline = models.CharField(max_length=80, blank=True)  # "" = the built-in wording for the kind
    verb = models.CharField(max_length=120, blank=True)
    logo = models.CharField(max_length=80, blank=True)  # /api/media/<hash>.<ext>
    signature = models.CharField(max_length=80, blank=True)
    signatory_name = models.CharField(max_length=80, blank=True)
    signatory_title = models.CharField(max_length=80, blank=True)
    footer_note = models.CharField(max_length=160, blank=True)
    active = models.BooleanField(default=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["org", "kind", "language"], name="uniq_cert_template_scope"),
            models.UniqueConstraint(
                fields=["kind", "language"],
                condition=models.Q(org__isnull=True),
                name="uniq_cert_template_platform",
            ),
        ]
