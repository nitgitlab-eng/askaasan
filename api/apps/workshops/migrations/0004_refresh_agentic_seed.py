from django.db import migrations


def refresh(apps, schema_editor):
    """M2: the agentic workshop's agent_build stage and final.agent_tests (seed is idempotent, matched by slug)."""
    from apps.workshops.content import seed

    seed(apps, schema_editor)


class Migration(migrations.Migration):
    dependencies = [("workshops", "0003_agent_servers")]

    operations = [migrations.RunPython(refresh, migrations.RunPython.noop)]
