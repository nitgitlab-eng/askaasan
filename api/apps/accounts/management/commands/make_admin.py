from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User


class Command(BaseCommand):
    help = "Give an existing user access to the Aasan admin console."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--revoke", action="store_true")
        parser.add_argument(
            "--role",
            action="append",
            choices=["superadmin", "support", "finance", "content"],
            help="Limit to these admin roles (repeatable). Default: superadmin.",
        )

    def handle(self, email, revoke, role=None, **opts):
        from apps.accounts.models import StaffRole

        user = User.objects.filter(email=email.lower()).first()
        if not user:
            raise CommandError(f"No user with email {email}")
        user.is_staff = not revoke
        user.save(update_fields=["is_staff"])
        if revoke:
            StaffRole.objects.filter(user=user).delete()
        else:
            StaffRole.objects.update_or_create(
                user=user, defaults={"roles": sorted(set(role or ["superadmin"]))}
            )
        self.stdout.write(
            self.style.SUCCESS(f"{email}: admin console access {'revoked' if revoke else 'granted'}")
        )
