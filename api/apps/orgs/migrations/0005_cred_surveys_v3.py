# Surveys v3 (cred builder): knowledge-test mode + retakes. Only this builder's operations.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orgs", "0004_membership_fields_membership_seat_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="survey", name="cooldown_minutes", field=models.PositiveIntegerField(default=0)
        ),
        migrations.AddField(
            model_name="survey", name="kind", field=models.CharField(default="survey", max_length=8)
        ),
        migrations.AddField(
            model_name="survey", name="max_attempts", field=models.PositiveSmallIntegerField(default=1)
        ),
        migrations.AddField(
            model_name="survey", name="pass_mark", field=models.PositiveSmallIntegerField(default=60)
        ),
        migrations.AddField(
            model_name="survey", name="show_review", field=models.BooleanField(default=False)
        ),
        migrations.AddField(
            model_name="surveyresponse", name="attempt", field=models.PositiveSmallIntegerField(default=1)
        ),
        migrations.AddField(
            model_name="surveyresponse", name="max_score", field=models.FloatField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="surveyresponse", name="passed", field=models.BooleanField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="surveyresponse", name="score", field=models.FloatField(blank=True, null=True)
        ),
        migrations.RemoveConstraint(model_name="surveyresponse", name="uniq_survey_response"),
        migrations.AddConstraint(
            model_name="surveyresponse",
            constraint=models.UniqueConstraint(
                fields=("survey", "respondent_key", "attempt"), name="uniq_survey_response_attempt"
            ),
        ),
    ]
