"""Write training records for completions that happened before records existed (C3). Idempotent: an existing record
is never touched, so it can be re-run any time. Backfilled rows are marked `backfilled` and send no webhooks.

  manage.py backfill_training_records             # every organisation
  manage.py backfill_training_records --org acme  # one organisation (slug)
"""

from django.core.management.base import BaseCommand, CommandError

from apps.integrations import hooks
from apps.orgs.models import Organization, SurveyResponse
from apps.orgs.records import record_completion


class Command(BaseCommand):
    help = "Create missing training records from past completions (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--org", help="Only this organisation (slug)")

    def handle(self, *args, **opts):
        orgs = Organization.objects.all()
        if opts.get("org"):
            orgs = orgs.filter(slug=opts["org"])
            if not orgs.exists():
                raise CommandError(f"no organisation {opts['org']!r}")
        made = 0
        for org in orgs.iterator():
            made += self._org(org)
        self.stdout.write(self.style.SUCCESS(f"{made} training record(s) created"))

    def _org(self, org) -> int:
        from apps.orgs.api import _assignment_learners
        from apps.roleplay.models import RolePlaySession
        from apps.workshops.models import WorkshopSession

        found = []
        for a in org.assignments.filter(curriculum__isnull=False).select_related("curriculum"):
            for m in _assignment_learners(a).select_related("user"):
                found += [c for c in hooks.course_completions(m.user, a.curriculum) if c.org.id == org.id]
        for sid in (
            RolePlaySession.objects.filter(assignment__org=org, status=RolePlaySession.Status.COMPLETED)
            .order_by("ended_at", "id")
            .values_list("id", flat=True)
        ):  # the first completion is the record
            found += hooks.roleplay_completions(sid)
        for sid in WorkshopSession.objects.filter(run__org=org, passed=True).values_list("id", flat=True):
            found += hooks.workshop_completions(sid)
        for rid in (
            SurveyResponse.objects.filter(
                survey__org=org, survey__kind="test", passed=True, user__isnull=False
            )
            .order_by("submitted_at", "id")
            .values_list("id", flat=True)
        ):
            found += hooks.knowledge_test_completions(rid)
        made = 0
        for c in found:
            c.backfilled = True
            made += record_completion(c)[1]
        return made
