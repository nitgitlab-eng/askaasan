from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Give (or --revoke) Creator Lab access."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--revoke", action="store_true")

    def handle(self, email, revoke, **opts):
        user = User.objects.filter(email=email.lower()).first()
        if not user:
            raise CommandError(f"No user with email {email}")
        user.is_creator = not revoke
        user.save(update_fields=["is_creator"])
        self.stdout.write(
            self.style.SUCCESS(f"{email}: Creator Lab access {'revoked' if revoke else 'granted'}")
        )
