from django.core.management.base import BaseCommand

from apps.accounts.study_reminders import send_due


class Command(BaseCommand):
    help = "In-app + email study reminders at each learner's chosen time. Run every 15 min (Celery beat does it in Docker)."

    def handle(self, *args, **opts):
        self.stdout.write(f"sent {send_due()}")
