from django.db import migrations


def backfill(apps, schema_editor):
    """Staff without a role row used to count as superadmins. Access now needs a row, so keep theirs as it was."""
    User = apps.get_model("accounts", "User")
    StaffRole = apps.get_model("accounts", "StaffRole")
    have = StaffRole.objects.values_list("user_id", flat=True)
    StaffRole.objects.bulk_create(
        [
            StaffRole(user_id=pk, roles=["superadmin"])
            for pk in User.objects.filter(is_staff=True, is_superuser=False)
            .exclude(pk__in=have)
            .values_list("pk", flat=True)
        ]
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0012_reminders")]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
