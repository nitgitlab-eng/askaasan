from django.apps import AppConfig


class CredentialsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.credentials"
    label = "credentials"

    def ready(self):
        # Set once for the whole process (every PDF renderer: certificates, invoices, teach
        # reports): reportlab must never fetch URLs or read files named in markup.
        from reportlab import rl_config

        from . import signals  # noqa: F401 — auto-issue course certificates on completion

        rl_config.trustedHosts, rl_config.trustedSchemes = [], []
