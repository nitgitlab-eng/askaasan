from django.db import migrations


def refresh(apps, schema_editor):
    """M5: the prompt-engineering workshop's "Your real task" becomes a graded `build` stage (seed is idempotent)."""
    from apps.workshops.content import seed

    seed(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("workshops", "0005_public_workshops")]

    operations = [migrations.RunPython(refresh, migrations.RunPython.noop)]
