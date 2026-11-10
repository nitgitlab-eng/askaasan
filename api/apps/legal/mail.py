"""Email backend that uses the SMTP settings from the admin console, falling back to the .env backend."""

from email.utils import formataddr

from django.conf import settings
from django.core.mail import get_connection
from django.core.mail.backends.base import BaseEmailBackend


def _smtp_connection(cfg, fail_silently=False):
    return get_connection(
        "django.core.mail.backends.smtp.EmailBackend",
        fail_silently=fail_silently,
        host=cfg.host,
        port=cfg.port,
        username=cfg.username or None,
        password=cfg.password() or None,
        use_tls=cfg.security == "tls",
        use_ssl=cfg.security == "ssl",
        timeout=20,
    )


class ConfigurableEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        from .models import MailConfig

        cfg = MailConfig.objects.filter(pk=1).first()
        if cfg and cfg.ready:
            sender = formataddr((cfg.from_name, cfg.from_email))
            for m in email_messages:
                if not m.from_email or m.from_email == settings.DEFAULT_FROM_EMAIL:
                    m.from_email = sender
            return _smtp_connection(cfg, self.fail_silently).send_messages(email_messages)
        return get_connection(
            settings.EMAIL_FALLBACK_BACKEND, fail_silently=self.fail_silently
        ).send_messages(email_messages)


# Backends that accept a message without delivering it anywhere a person can read it.
_NOT_DELIVERING = {
    "django.core.mail.backends.console.EmailBackend",
    "django.core.mail.backends.dummy.EmailBackend",
    "django.core.mail.backends.filebased.EmailBackend",
}
EMAIL_NOT_CONFIGURED = "email_not_configured"


def mail_ready() -> bool:
    """True when an email we send would really reach an inbox: admin-console SMTP, or a real .env backend.
    (locmem counts as ready — it is what the test suite reads delivered mail from.)"""
    from .models import MailConfig

    backend = settings.EMAIL_BACKEND
    if backend != "apps.legal.mail.ConfigurableEmailBackend":
        return backend not in _NOT_DELIVERING
    cfg = MailConfig.objects.filter(pk=1).first()
    if cfg and cfg.ready:
        return True
    return getattr(settings, "EMAIL_FALLBACK_BACKEND", "") not in _NOT_DELIVERING
