from django.db import migrations


def seed(apps, schema_editor):
    from apps.workshops.content import seed as seed_all

    seed_all(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("workshops", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
