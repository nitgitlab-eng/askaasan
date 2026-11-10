from django.core.management.base import BaseCommand

from apps.billing.reminders import send_due


class Command(BaseCommand):
    help = "Email + in-app reminders for plans ending soon or just ended. Run daily (Celery beat does this in Docker)."

    def handle(self, *args, **opts):
        self.stdout.write(str(send_due()))
