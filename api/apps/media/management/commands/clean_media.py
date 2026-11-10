from django.core.management.base import BaseCommand

from apps.media.cleanup import sweep, sweep_lectures


class Command(BaseCommand):
    help = "Delete unreferenced, ownerless lesson-image and lecture files (runs daily from Celery beat). --dry-run to preview."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        self.stdout.write(str(sweep(dry_run=opts["dry_run"])))
        self.stdout.write(str(sweep_lectures(dry_run=opts["dry_run"])))
