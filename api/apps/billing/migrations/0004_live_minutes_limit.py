from django.db import migrations

LIVE = {"free": 10, "plus_month": 60, "plus_year": 60}


def add(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for code, minutes in LIVE.items():
        for p in Plan.objects.filter(code=code):
            if "live_minutes_per_day" not in p.limits:
                p.limits = {**p.limits, "live_minutes_per_day": minutes}
                p.save(update_fields=["limits"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_entitlement_reminded_end_at_and_more")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
