from django.db import migrations


def run(apps, schema_editor):
    from apps.paths.catalog import seed

    seed(apps)


class Migration(migrations.Migration):
    dependencies = [("paths", "0003_jr_ladder_plan")]
    operations = [migrations.RunPython(run, migrations.RunPython.noop)]
