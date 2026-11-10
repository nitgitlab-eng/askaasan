from django.db import migrations


def run(apps, schema_editor):
    from apps.paths.catalog import seed

    seed(apps)


class Migration(migrations.Migration):
    dependencies = [("paths", "0001_initial")]
    operations = [migrations.RunPython(run, migrations.RunPython.noop)]
