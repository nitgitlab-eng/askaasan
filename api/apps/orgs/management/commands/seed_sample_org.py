"""A realistic sample school to explore the organisation features: admin and teachers, two classes, 24 students with
varied progress, an assigned course, an open survey with answers, workshop seats and its own certificate design.

Safe to run on any environment (unlike seed_demo it doesn't need DEBUG): every sample account is
sample.<name>@aasan.test, so Admin → System check flags them for removal before going live. Re-running resets the
sample school instead of duplicating it. Remove everything with --remove.

  manage.py seed_sample_org --owner you@example.com        # you become the school's owner
  manage.py seed_sample_org --remove
"""

import random
import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

SLUG = "sunrise-sample-school"
DOMAIN = "@aasan.test"
STAFF = [
    ("sample.lakshmi", "Lakshmi Narayanan", "admin"),
    ("sample.meena", "Meena Sundaram", "manager"),
    ("sample.arjun", "Arjun Prakash", "manager"),
]
STUDENTS = [
    "Aarav Kumar",
    "Divya Ramesh",
    "Karthik Raja",
    "Priya Senthil",
    "Rahul Menon",
    "Sneha Iyer",
    "Vikram Balaji",
    "Ananya Krishnan",
    "Harini Murugan",
    "Gokul Venkat",
    "Nila Shankar",
    "Surya Prakash",
    "Keerthana Mohan",
    "Ashwin Ravi",
    "Pooja Chandran",
    "Dinesh Kannan",
    "Swathi Gopal",
    "Manoj Selvam",
    "Lavanya Arun",
    "Naveen Pandian",
    "Revathi Subramani",
    "Sanjay Natarajan",
    "Yamini Rajan",
    "Bharath Ganesan",
]
INTERESTS = [
    "Using AI for my science project",
    "Making a website",
    "AI for drawing and design",
    "Coding games",
    "How chatbots work",
    "Preparing for engineering entrance",
    "Spoken English with AI",
    "Data and charts",
]


def _email(handle: str) -> str:
    return f"{handle}{DOMAIN}"


def _student_handle(name: str) -> str:
    first, last = name.lower().split()
    return f"sample.{first}.{last[0]}"


class Command(BaseCommand):
    help = (
        "Create (or reset) a sample school with teachers, classes, students, progress, a survey and branding."
    )

    def add_arguments(self, parser):
        parser.add_argument("--owner", help="Email of an existing account to make the school's owner")
        parser.add_argument(
            "--remove", action="store_true", help="Delete the sample school and its sample accounts"
        )
        parser.add_argument("--seed", type=int, default=7, help="Random seed for the sample progress")

    def handle(self, *args, **opts):
        if opts["remove"]:
            self._remove()
            return
        owner = None
        if opts["owner"]:
            from apps.accounts.models import User

            owner = User.objects.filter(email=opts["owner"].strip().lower()).first()
            if not owner:
                raise CommandError("No account with that email — sign up first, then run this again.")
        random.seed(opts["seed"])
        password = "Sample-" + secrets.token_urlsafe(9)
        with transaction.atomic():
            self._remove(quiet=True)
            summary = self._build(owner, password)
        self.stdout.write(self.style.SUCCESS(summary))
        self.stdout.write(f"SAMPLE_PASSWORD={password}")

    # ── building ─────────────────────────────────────────────────────

    def _user(self, handle, name, password):
        from apps.accounts.models import User
        from apps.legal.models import TERMS_VERSION

        u = User.objects.create_user(_email(handle), password)
        u.email_verified = True
        u.terms_version, u.terms_accepted_at, u.age_band = TERMS_VERSION, timezone.now(), "adult"
        u.save()
        p = u.profile
        p.display_name, p.onboarding_completed = name, True
        p.save()
        return u

    def _build(self, owner, password) -> str:
        from apps.credentials.models import CertificateTemplate
        from apps.learning.models import Enrollment
        from apps.learning.showcase import build_showcase
        from apps.orgs.models import Assignment, Group, Membership, Organization, Survey
        from apps.orgs.templates_lib import SURVEY_TEMPLATES

        staff = {h: self._user(h, n, password) for h, n, _ in STAFF}
        admin = staff["sample.lakshmi"]
        org = Organization.objects.create(
            name="Sunrise Sample School",
            slug=SLUG,
            kind=Organization.Kind.SCHOOL,
            display_name="Sunrise Sample School",
            description="A sample school to explore Aasan's organisation features (classes, assignments, reports).",
            brand_color="#0f766e",
            created_by=owner or admin,
            features={"workshops": True},
            workshop_seats=60,
        )
        if owner:
            Membership.objects.create(org=org, user=owner, role="owner")
        members = {h: Membership.objects.create(org=org, user=staff[h], role=r) for h, _, r in STAFF}

        everyone = Group.objects.create(org=org, name="Everyone")
        classes = {
            "Class 9 A": (Group.objects.create(org=org, name="Class 9 A"), members["sample.meena"]),
            "Class 10 A": (Group.objects.create(org=org, name="Class 10 A"), members["sample.arjun"]),
        }
        for grp, teacher_m in classes.values():
            grp.members.add(teacher_m)

        course = build_showcase(staff["sample.meena"])
        course.title = "Sunrise: Meet every activity type"
        course.save(update_fields=["title"])
        due = timezone.now() + timedelta(days=10)
        for name, (grp, _) in classes.items():
            Assignment.objects.create(
                org=org,
                group=grp,
                curriculum=course,
                due_at=due,
                note=f"{name}: try every activity before the weekend.",
                created_by=staff["sample.meena"],
            )

        students = []
        for i, name in enumerate(STUDENTS):
            u = self._user(_student_handle(name), name, password)
            m = Membership.objects.create(org=org, user=u, role="learner")
            everyone.members.add(m)
            grp = classes["Class 9 A" if i % 2 == 0 else "Class 10 A"][0]
            grp.members.add(m)
            Enrollment.objects.create(user=u, curriculum=course)
            students.append(u)

        certified = self._progress(course, students)

        tpl = SURVEY_TEMPLATES["ai_readiness"]
        survey = Survey.objects.create(
            org=org,
            title=tpl["title"],
            description=tpl["description"],
            questions=tpl["questions"],
            anonymous=True,
            status="open",
            created_by=staff["sample.meena"],
        )
        answered = self._survey_answers(survey, students)

        CertificateTemplate.objects.create(
            org=org,
            layout="modern",
            colors={"accent": "#0f766e", "gold": "#b8860b", "ink": "#1f2a44", "paper": "#fffaf2"},
            signatory_name="Lakshmi Narayanan",
            signatory_title="Principal (sample)",
            footer_note="Sunrise Sample School",
            updated_by=admin,
        )
        codes = ", ".join(f"{n}: {g.join_code}" for n, (g, _) in classes.items())
        return (
            f"Sample school ready: {org.name} (/orgs → {SLUG})\n"
            f"  Owner: {'your account' if owner else 'none (run with --owner to add yourself)'}\n"
            f"  Admin: {_email('sample.lakshmi')}   Teachers: {_email('sample.meena')}, {_email('sample.arjun')}\n"
            f"  Students: {len(students)} in 2 classes ({codes})\n"
            f"  Course '{course.title}' assigned to both classes; {certified} students finished it and got certificates\n"
            f"  Survey '{survey.title}' open with {answered} answers; workshops on with 60 seats a month\n"
            f"  Certificate design: modern layout, signed by the principal\n"
            f"  All sample accounts share one password (printed below). They end in {DOMAIN}: remove them before go-live."
        )

    def _progress(self, course, students) -> int:
        """Varied, believable progress: some finished, most part-way, a few not started."""
        from apps.game import services as game
        from apps.learning.models import ActivityAttempt, Subsection, UserSubsectionState

        lessons = list(
            Subsection.objects.filter(section__curriculum=course).order_by("section__order", "order")
        )
        certified = 0
        for i, u in enumerate(students):
            if i % 6 == 5:
                continue  # not started yet
            done = len(lessons) if i % 4 == 0 else random.randint(1, max(1, len(lessons) - 1))
            skill = random.uniform(0.55, 1.0)
            for les in lessons[:done]:
                acts = list(les.activities.filter(kind="lesson"))
                scores = []
                for a in acts:
                    sc = round(min(1.0, max(0.0, random.gauss(skill, 0.15))), 2)
                    if i % 4 == 0:
                        sc = max(sc, 0.8)  # the finishers passed every lesson
                    ActivityAttempt.objects.create(user=u, activity=a, answer={}, score=sc, correct=sc >= 0.6)
                    scores.append(sc)
                score = round(sum(scores) / len(scores), 3) if scores else None
                now = timezone.now() - timedelta(days=random.randint(0, 9), hours=random.randint(0, 20))
                UserSubsectionState.objects.create(
                    user=u, subsection=les, status="completed", score=score, started_at=now, completed_at=now
                )
                game.on_lesson_complete(u, les, score or 0.0)
            if done == len(lessons):
                from apps.credentials.models import Certificate

                certified += Certificate.objects.filter(user=u, curriculum=course).exists()
        return certified

    def _survey_answers(self, survey, students) -> int:
        from apps.orgs.models import SurveyResponse
        from apps.orgs.surveys import _respondent_key, clean_answer

        n = 0
        for u in students[: int(len(students) * 0.75)]:
            raw = {
                "q1": random.choice(["Never", "Monthly", "Weekly", "Weekly", "Daily"]),
                "q2": random.randint(2, 5),
                "q3": random.randint(5, 10),
                "q4": random.choice(INTERESTS),
            }
            answers = {q["id"]: clean_answer(q, raw[q["id"]]) for q in survey.questions}
            SurveyResponse.objects.create(
                survey=survey, respondent_key=_respondent_key(survey, u), answers=answers
            )
            n += 1
        return n

    # ── removing ─────────────────────────────────────────────────────

    def _remove(self, quiet=False):
        from apps.accounts.models import User
        from apps.learning.models import Curriculum
        from apps.orgs.models import Organization

        handles = [h for h, _, _ in STAFF] + [_student_handle(n) for n in STUDENTS]
        users = User.objects.filter(email__in=[_email(h) for h in handles])
        Curriculum.objects.filter(owner__in=users).delete()
        n_org, _ = Organization.objects.filter(slug=SLUG).delete()
        n_users = users.count()
        users.delete()
        if not quiet:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Removed the sample school ({bool(n_org)}) and {n_users} sample accounts."
                )
            )
