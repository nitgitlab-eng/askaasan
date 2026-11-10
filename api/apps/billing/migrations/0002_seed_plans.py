from django.db import migrations

FREE = {"ai_courses_per_month": 2, "mentor_messages_per_day": 30, "documents": 3, "voice_minutes_per_day": 10}
PLUS = {
    "ai_courses_per_month": 20,
    "mentor_messages_per_day": 300,
    "documents": 50,
    "voice_minutes_per_day": 60,
}
PLANS = [
    {
        "code": "free",
        "name": "Free",
        "description": "Start learning with Kili",
        "price_paise": 0,
        "period_days": 0,
        "limits": FREE,
        "sort": 0,
    },
    {
        "code": "plus_month",
        "name": "Aasan Plus · Monthly",
        "description": "More courses, chats and voice time",
        "price_paise": 14900,
        "period_days": 30,
        "limits": PLUS,
        "sort": 1,
    },
    {
        "code": "plus_year",
        "name": "Aasan Plus · Yearly",
        "description": "Best value for the whole school year",
        "price_paise": 149900,
        "period_days": 365,
        "limits": PLUS,
        "badge": "2 months free",
        "sort": 2,
    },
]


def seed(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for p in PLANS:
        Plan.objects.get_or_create(code=p["code"], defaults=p)


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
