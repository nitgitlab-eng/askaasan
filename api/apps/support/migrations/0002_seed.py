from django.db import migrations


def seed(apps, schema_editor):
    from apps.support.articles import seed as do

    do(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("support", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
