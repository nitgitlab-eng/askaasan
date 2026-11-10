"""Fill `last_login` ("Last seen" in the admin console) from each account's newest session token. Sign-in never set it
before, so every account showed "—" and "0 seen this week"; from now on `tokens.touch_last_seen` keeps it current."""

from django.db import migrations
from django.db.models import Max


def backfill(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    OutstandingToken = apps.get_model("token_blacklist", "OutstandingToken")
    latest = (
        OutstandingToken.objects.filter(user__isnull=False, user__last_login__isnull=True)
        .values("user_id")
        .annotate(seen=Max("created_at"))
    )
    for row in latest.iterator():
        User.objects.filter(pk=row["user_id"], last_login__isnull=True).update(last_login=row["seen"])


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0007_adminauditlog_staffrole"),
        ("token_blacklist", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
