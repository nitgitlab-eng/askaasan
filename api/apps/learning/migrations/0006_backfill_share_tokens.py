import secrets

from django.db import migrations


def backfill(apps, schema_editor):
    """Give every existing course its own token (a column default would give
    them all the same value and break the unique constraint added next)."""
    Curriculum = apps.get_model("learning", "Curriculum")
    for cur in Curriculum.objects.filter(share_token__isnull=True).only("id"):
        cur.share_token = secrets.token_urlsafe(9)
        cur.save(update_fields=["share_token"])


class Migration(migrations.Migration):
    dependencies = [("learning", "0005_activity_source_curriculum_catalog_note_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
