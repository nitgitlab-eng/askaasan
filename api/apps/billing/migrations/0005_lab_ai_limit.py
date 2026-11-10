from django.db import migrations

LAB = {"free": 20, "plus_month": 200, "plus_year": 200}


def add(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for code, n in LAB.items():
        for p in Plan.objects.filter(code=code):
            if "lab_ai_per_day" not in p.limits:
                p.limits = {**p.limits, "lab_ai_per_day": n}
                p.save(update_fields=["limits"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0004_live_minutes_limit")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
