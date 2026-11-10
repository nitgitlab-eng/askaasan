from django.core.management.base import BaseCommand

from apps.workshops.content import seed


class Command(BaseCommand):
    help = "Create or refresh the launch workshop templates (idempotent; matched by slug)."

    def handle(self, *args, **options):
        n = seed()
        self.stdout.write(self.style.SUCCESS(f"Seeded {n} workshops."))
