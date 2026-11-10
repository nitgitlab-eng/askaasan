from django.db import models

# Bump when the Terms or Privacy Policy change materially; everyone is asked to accept again.
TERMS_VERSION = "2026-10-16"
DPA_VERSION = "2026-10-17"


class SiteInfo(models.Model):
    """Singleton (pk=1): the business details shown on the legal and contact pages. Edited in the admin console."""

    brand = models.CharField(max_length=60, default="Aasan")
    legal_name = models.CharField(max_length=160, blank=True)  # registered business / company name
    address = models.TextField(blank=True)
    city = models.CharField(max_length=60, default="Chennai")  # courts with jurisdiction
    support_email = models.EmailField(blank=True)
    phone = models.CharField(max_length=24, blank=True)
    grievance_officer = models.CharField(max_length=120, blank=True)
    grievance_email = models.EmailField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    state = models.CharField(max_length=40, default="Tamil Nadu")  # place of supply (CGST+SGST vs IGST)
    hsn_sac = models.CharField(max_length=8, default="999293")  # SAC: commercial training / coaching services
    refund_days = models.PositiveSmallIntegerField(default=7)
    updated_at = models.DateTimeField(auto_now=True)


class MailConfig(models.Model):
    """Singleton (pk=1): outgoing email (SMTP) set in the admin console. Password is Fernet-encrypted."""

    enabled = models.BooleanField(default=True)
    host = models.CharField(max_length=200, blank=True)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=8, default="tls")  # tls (STARTTLS) | ssl | none
    username = models.CharField(max_length=200, blank=True)
    encrypted_password = models.TextField(blank=True)
    from_email = models.EmailField(blank=True)
    from_name = models.CharField(max_length=80, default="Aasan")
    updated_at = models.DateTimeField(auto_now=True)

    def password(self) -> str:
        from apps.providers import crypto

        return crypto.decrypt(self.encrypted_password) if self.encrypted_password else ""

    @property
    def ready(self) -> bool:
        return self.enabled and bool(self.host and self.from_email)
