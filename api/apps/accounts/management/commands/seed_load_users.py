"""Create throwaway learner accounts for the load test (api/scripts/load_test.py) and write their JWTs to a file.

    uv run python manage.py seed_load_users --count 600 --prefix load --out /tmp/load-tokens.json \\
        --i-know-this-is-not-production [--create-workshop-run | --workshop-run ID] [--course ID|auto] [--org SLUG]

Accounts are `<prefix>NNNN@load.aasan.test`: verified, consented (adult), onboarded, no usable password. Re-running is
safe: existing accounts are reused and repaired, today's mentor-message usage is cleared (so a second run doesn't hit
the free plan's daily cap) and fresh tokens are minted. Tokens are written to `--out` with mode 600 and never printed.

With a workshop run, every account is enrolled and gets a started session (prerequisites ticked), so the harness can
open the workshop socket straight away; the file then carries `run_id` and `session_id` per account. Sessions are
recreated on every run (a learner who reached the final stage last time starts over), unless --keep-sessions.
"""

import json
import os
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile, User, UserPreferences

DOMAIN = "load.aasan.test"


def _tokens(user) -> dict:
    """issue_tokens has returned a dict {access, refresh}; accept an (access, refresh) tuple too."""
    from apps.accounts.tokens import issue_tokens

    out = issue_tokens(user)
    if isinstance(out, dict):
        return {"access": str(out["access"]), "refresh": str(out["refresh"])}
    access, refresh = out[0], out[1]
    return {"access": str(access), "refresh": str(refresh)}


def _write_private(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


class Command(BaseCommand):
    help = "Create verified, onboarded load-test learners and write their tokens to a JSON file (never production)."

    def add_arguments(self, p):
        p.add_argument("--count", type=int, default=600)
        p.add_argument("--prefix", default="load")
        p.add_argument("--out", required=True, help="token file (JSON list), written with mode 600")
        p.add_argument("--workshop-run", type=int, help="enrol everyone in this run and start a session each")
        p.add_argument(
            "--create-workshop-run",
            action="store_true",
            help="create a live, free public run of a published workshop for the load test and use it",
        )
        p.add_argument(
            "--workshop", default="prompt-engineering", help="workshop slug for --create-workshop-run"
        )
        p.add_argument("--keep-sessions", action="store_true", help="reuse existing workshop sessions")
        p.add_argument("--course", default="", help="curriculum id to enrol everyone in, or 'auto'")
        p.add_argument("--org", default="", help="organization slug: add everyone as a learner")
        p.add_argument("--i-know-this-is-not-production", action="store_true", dest="not_prod")
        p.add_argument("--allow-non-debug", action="store_true", help="run with DEBUG off (a staging stack)")

    def handle(self, *args, **o):
        if not o["not_prod"]:
            raise CommandError("Refusing: pass --i-know-this-is-not-production (this creates fake accounts).")
        if not settings.DEBUG and not o["allow_non_debug"]:
            raise CommandError("Refusing: DEBUG is off. Pass --allow-non-debug for a non-production stack.")
        count, prefix = o["count"], o["prefix"].strip().lower()
        if count < 1 or count > 20000:
            raise CommandError("--count must be between 1 and 20000")
        if not prefix.isalnum():
            raise CommandError("--prefix must be letters and digits only")
        if o["workshop_run"] and o["create_workshop_run"]:
            raise CommandError("Use either --workshop-run or --create-workshop-run, not both.")

        users = self._users(prefix, count)
        course = self._course(o["course"])
        run = self._run(o)
        with transaction.atomic():
            self._reset_usage(users)
            if course:
                self._enrol_course(users, course)
            if o["org"]:
                self._join_org(users, o["org"])
            sessions = self._sessions(users, run, keep=o["keep_sessions"]) if run else {}

        rows = []
        for u in users:
            row = {"email": u.email, **_tokens(u)}
            if run:
                row["run_id"] = run.id
                row["session_id"] = sessions[u.id]
            if course:
                row["course_id"] = course.id
            rows.append(row)
        out = Path(o["out"]).expanduser()
        _write_private(out, rows)
        extra = []
        if run:
            extra.append(f"workshop run #{run.id} ({run.workshop.slug})")
        if course:
            extra.append(f"course #{course.id}")
        if o["org"]:
            extra.append(f"org {o['org']}")
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(rows)} load users ready ({prefix}0000@{DOMAIN}…)"
                + (f"; {', '.join(extra)}" if extra else "")
                + f". Tokens written to {out} (mode 600)."
            )
        )

    # ── accounts ─────────────────────────────────────────────────────
    def _users(self, prefix: str, count: int) -> list[User]:
        from apps.legal.models import TERMS_VERSION

        emails = [f"{prefix}{i:04d}@{DOMAIN}" for i in range(count)]
        now = timezone.now()
        with transaction.atomic():
            have = set(User.objects.filter(email__in=emails).values_list("email", flat=True))
            new = []
            for e in emails:
                if e in have:
                    continue
                u = User(
                    email=e,
                    email_verified=True,
                    terms_version=TERMS_VERSION,
                    terms_accepted_at=now,
                    age_band="adult",
                )
                u.set_unusable_password()
                new.append(u)
            User.objects.bulk_create(new, batch_size=500)  # skips post_save: profiles are made below
            qs = User.objects.filter(email__in=emails)
            qs.filter(email_verified=False).update(email_verified=True)
            qs.exclude(terms_version=TERMS_VERSION).update(
                terms_version=TERMS_VERSION, terms_accepted_at=now, age_band="adult", guardian_email=""
            )
            qs.filter(is_active=False).update(is_active=True)
            users = list(qs.order_by("email"))
            ids = [u.id for u in users]
            has_profile = set(Profile.objects.filter(user_id__in=ids).values_list("user_id", flat=True))
            Profile.objects.bulk_create(
                [
                    Profile(
                        user=u,
                        display_name=f"Load {u.email.split('@')[0]}",
                        domain="ai",
                        goals=["learn"],
                        onboarding_completed=True,
                    )
                    for u in users
                    if u.id not in has_profile
                ],
                batch_size=500,
            )
            Profile.objects.filter(user_id__in=ids, onboarding_completed=False).update(
                onboarding_completed=True
            )
            has_prefs = set(UserPreferences.objects.filter(user_id__in=ids).values_list("user_id", flat=True))
            UserPreferences.objects.bulk_create(
                [UserPreferences(user=u) for u in users if u.id not in has_prefs], batch_size=500
            )
        return users

    def _reset_usage(self, users):
        from apps.billing.models import UsageEvent

        UsageEvent.objects.filter(user__in=users, metric="mentor_message").delete()

    # ── optional extras ──────────────────────────────────────────────
    def _course(self, ref: str):
        if not ref:
            return None
        from apps.learning.models import Curriculum

        if ref == "auto":  # learners only see a shared course once it is published
            cur = Curriculum.objects.filter(published_at__isnull=False).order_by("-published_at").first()
            if not cur:
                raise CommandError("--course auto: no published course yet (try seed_demo --full)")
            return cur
        try:
            cur = Curriculum.objects.get(pk=int(ref))
        except (ValueError, Curriculum.DoesNotExist) as e:
            raise CommandError(f"No curriculum {ref}") from e
        if not cur.published_at:
            raise CommandError(f"Curriculum {ref} is not published, so enrolled learners could not open it")
        return cur

    def _enrol_course(self, users, course):
        from apps.learning.models import Enrollment

        have = set(
            Enrollment.objects.filter(curriculum=course, user__in=users).values_list("user_id", flat=True)
        )
        Enrollment.objects.bulk_create(
            [
                Enrollment(user=u, curriculum=course)
                for u in users
                if u.id not in have and u.id != course.owner_id
            ],
            batch_size=500,
        )

    def _join_org(self, users, slug):
        from apps.orgs.models import Membership, Organization

        org = Organization.objects.filter(slug=slug).first()
        if not org:
            raise CommandError(f"No organization {slug}")
        have = set(Membership.objects.filter(org=org, user__in=users).values_list("user_id", flat=True))
        Membership.objects.bulk_create(
            [Membership(org=org, user=u, role="learner") for u in users if u.id not in have], batch_size=500
        )

    def _run(self, o):
        from apps.workshops.models import Workshop, WorkshopRun

        if o["workshop_run"]:
            run = WorkshopRun.objects.select_related("workshop").filter(pk=o["workshop_run"]).first()
            if not run:
                raise CommandError(f"No workshop run {o['workshop_run']}")
            return run
        if not o["create_workshop_run"]:
            return None
        qs = Workshop.objects.filter(is_published=True)
        if not qs.exists():
            from apps.workshops.content import seed

            seed()
        w = qs.filter(slug=o["workshop"]).first()
        if not w:
            raise CommandError(f"No published workshop {o['workshop']}")
        return WorkshopRun.objects.create(
            workshop=w,
            audience=WorkshopRun.Audience.PUBLIC,
            starts_at=timezone.now() - timedelta(minutes=1),
            late_join_minutes=24 * 60,  # the harness may start well after seeding
            status=WorkshopRun.Status.LIVE,
            proctoring="off",
            price_paise=0,
        )

    def _sessions(self, users, run, *, keep: bool) -> dict[int, int]:
        from apps.workshops import services
        from apps.workshops.models import WorkshopEnrollment, WorkshopSession

        have = set(
            WorkshopEnrollment.objects.filter(run=run, user__in=users).values_list("user_id", flat=True)
        )
        WorkshopEnrollment.objects.bulk_create(
            [WorkshopEnrollment(run=run, user=u) for u in users if u.id not in have], batch_size=500
        )
        if not keep:
            WorkshopSession.objects.filter(run=run, user__in=users).delete()
        enrolments = {e.user_id: e for e in WorkshopEnrollment.objects.filter(run=run, user__in=users)}
        existing = {s.user_id: s for s in WorkshopSession.objects.filter(run=run, user__in=users)}
        keys = [p["key"] for p in run.workshop.prerequisites or []]
        stamp = timezone.now().isoformat()
        out = {}
        for u in users:
            s = existing.get(u.id) or WorkshopSession.objects.create(
                enrollment=enrolments[u.id], user=u, run=run
            )
            if not s.started_at:
                s.prereqs_done = {k: stamp for k in keys}
                s.save(update_fields=["prereqs_done"])
                s.run = run
                if code := services.start(s):
                    raise CommandError(f"Could not start a workshop session: {code}")
            out[u.id] = s.id
        return out
