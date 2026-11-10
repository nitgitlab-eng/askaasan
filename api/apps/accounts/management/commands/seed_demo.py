"""Create local demo accounts (and, with --full, demo content for every feature). DEV ONLY — refuses when DEBUG is off."""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User

DEMO_EMAIL = "kavya.demo@aasan.test"
DEMO_PASSWORD = "Kili#Demo-2026"
LEARNER_EMAIL = "meena.demo@aasan.test"


def _user(email, name, *, staff=False):
    from apps.legal.api import record_consent

    user = User.objects.filter(email=email).first() or User.objects.create_user(email)
    user.set_password(DEMO_PASSWORD)
    user.email_verified = True
    user.is_staff = user.is_staff or staff
    user.is_creator = user.is_creator or staff
    user.save()
    if staff:
        from apps.accounts.models import StaffRole

        StaffRole.objects.get_or_create(user=user, defaults={"roles": ["superadmin"]})
    user.profile.display_name = name
    user.profile.onboarding_completed = True
    user.profile.save()
    if not user.terms_version:
        record_consent(user, "adult")
    return user


class Command(BaseCommand):
    help = "Create (or reset) the demo accounts. --full also builds a showcase course with every activity type, a school, a class, an assignment and a survey."

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("seed_demo is for local development only")
        teacher = _user(DEMO_EMAIL, "கவ்யா", staff=True)
        if not opts["full"]:
            self.stdout.write(
                self.style.SUCCESS(f"Demo account ready: {DEMO_EMAIL} (password in seed_demo.py)")
            )
            return
        from apps.learning.models import Enrollment
        from apps.learning.showcase import build_showcase
        from apps.orgs.models import Assignment, Group, Membership, Organization, Survey
        from apps.orgs.templates_lib import SURVEY_TEMPLATES

        learner = _user(LEARNER_EMAIL, "Meena")
        course = build_showcase(teacher)
        org, _ = Organization.objects.get_or_create(
            slug="aasan-demo-school",
            defaults={"name": "Aasan Demo School", "kind": "school", "created_by": teacher},
        )
        Membership.objects.get_or_create(org=org, user=teacher, defaults={"role": "owner"})
        lm, _ = Membership.objects.get_or_create(org=org, user=learner, defaults={"role": "learner"})
        everyone = Group.objects.filter(org=org, name="Everyone").first() or Group.objects.create(
            org=org, name="Everyone"
        )
        cls = Group.objects.filter(org=org, name="Class 10 A").first() or Group.objects.create(
            org=org, name="Class 10 A"
        )
        everyone.members.add(lm)
        cls.members.add(lm)
        Assignment.objects.filter(org=org, curriculum__title=course.title).delete()
        Assignment.objects.create(
            org=org,
            group=cls,
            curriculum=course,
            due_at=timezone.now() + timedelta(days=7),
            note="Try every activity — it takes about 15 minutes.",
            created_by=teacher,
        )
        Enrollment.objects.get_or_create(user=learner, curriculum=course)
        tpl = SURVEY_TEMPLATES["ai_readiness"]
        if not Survey.objects.filter(org=org, title=tpl["title"]).exists():
            Survey.objects.create(
                org=org,
                title=tpl["title"],
                description=tpl["description"],
                questions=tpl["questions"],
                anonymous=True,
                status="open",
                created_by=teacher,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready.\n  Teacher/admin: {DEMO_EMAIL}\n  Learner: {LEARNER_EMAIL}\n  (passwords in seed_demo.py)\n"
                f"  Course: '{course.title}' (id {course.id}) — assigned to Class 10 A, due in 7 days\n"
                f"  School: /org/{org.slug}   Class code: {cls.join_code}   Survey: open"
            )
        )
