"""Concurrency regressions (R34 R35, S12 lock, XP award). These rely on SELECT ... FOR UPDATE, which SQLite ignores, so
they run only against Postgres (CI's api-postgres job sets DATABASE_URL). Real threads, real transactions."""

import threading
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections, transaction
from django.utils import timezone
from rest_framework.test import APIClient

pytestmark = [
    pytest.mark.skipif(connection.vendor != "postgresql", reason="needs Postgres row locks"),
    pytest.mark.django_db(transaction=True),
]
PW = "Harden#Race2026"
N = 8


def race(fn, n=N):
    """Run fn(i) in n threads released together; return the results (exceptions are returned, not raised)."""
    barrier, out = threading.Barrier(n), [None] * n

    def run(i):
        try:
            barrier.wait()
            out[i] = fn(i)
        except Exception as e:  # noqa: BLE001 - report it to the asserting thread
            out[i] = e
        finally:
            connections.close_all()  # each thread has its own connection

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


def _user(email, **kw):
    from apps.accounts.models import User

    return User.objects.create_user(email, PW, **kw)


def _free(limits):
    from apps.billing.models import Plan

    Plan.objects.update_or_create(code="free", defaults={"name": "Free", "price_paise": 0, "limits": limits})


def test_parallel_consume_never_passes_the_limit():
    from apps.billing.models import UsageEvent
    from apps.billing.services import PlanLimit, consume

    _free({"mentor_messages_per_day": 3})
    u = _user("race@x.in")

    def go(_):
        try:
            consume(u, "mentor_messages_per_day", "mentor_message")
            return True
        except PlanLimit:
            return False

    res = race(go)
    assert res.count(True) == 3, res
    assert UsageEvent.objects.filter(user=u, metric="mentor_message").count() == 3


def _org_with_seats(seats, learners):
    from apps.billing.models import OrgSubscription, Plan
    from apps.orgs.models import Membership, Organization

    org = Organization.objects.create(name="Race", slug="race", kind="school")
    plan = Plan.objects.create(code="seat_race", name="Seat", price_paise=10000, period_days=30, limits={})
    now = timezone.now()
    OrgSubscription.objects.create(
        org=org, plan=plan, seats=seats, starts_at=now, ends_at=now + timedelta(days=30)
    )
    ms = [
        Membership.objects.create(org=org, user=_user(f"k{i}@race.in"), role="learner")
        for i in range(learners)
    ]
    return org, ms


def test_parallel_seat_toggles_never_exceed_paid_seats():
    from apps.billing.services import seats_total
    from apps.orgs.models import Membership

    org, ms = _org_with_seats(2, N)
    owner = _user("owner@race.in")
    Membership.objects.create(org=org, user=owner, role="owner")

    def go(i):
        c = APIClient()
        c.force_authenticate(owner)
        return c.post(
            "/api/billing/orgs/race/", {"membership_id": ms[i].id, "seat": True}, format="json"
        ).status_code

    codes = race(go)
    assert codes.count(200) == 2 and codes.count(409) == N - 2, codes
    assert Membership.objects.filter(org=org, seat=True).count() == seats_total(org) == 2


def test_parallel_assign_seats_fills_exactly_the_paid_count():
    from apps.billing.services import assign_seats
    from apps.orgs.models import Membership

    org, _ = _org_with_seats(3, N)
    res = race(lambda _: assign_seats(org))
    assert sum(r for r in res if isinstance(r, int)) == 3, res
    assert Membership.objects.filter(org=org, seat=True).count() == 3


def test_parallel_transcribe_respects_voice_minutes(monkeypatch):
    import apps.providers.voice_api as v
    from apps.providers.models import ProviderConfig, UsageCounter

    ProviderConfig.objects.create(
        capability="stt", provider="fake", model="x", limits={"stt_seconds_per_day": 0}
    )
    monkeypatch.setattr(v, "needs_key", lambda *a: False)
    _free({"voice_minutes_per_day": 1})
    u = _user("voice@race.in")

    def go(i):
        c = APIClient()
        c.force_authenticate(u)
        clip = SimpleUploadedFile(f"{i}.webm", b"0" * 100, "audio/webm")
        return c.post(
            "/api/voice/transcribe/", {"audio": clip, "seconds": "40"}, format="multipart"
        ).status_code

    codes = race(go)
    assert codes.count(200) == 1 and codes.count(402) == N - 1, codes
    assert UsageCounter.objects.get(user=u, metric="stt_seconds").amount == 40


def test_parallel_award_credits_once():
    from apps.game.models import PlayerStats, XPEvent
    from apps.game.services import award

    u = _user("xp@race.in")

    def go(_):
        with transaction.atomic():
            return award(u, "lesson_complete", ref="lesson:race", xp=10, coins=1)

    res = race(go)
    assert sum(1 for r in res if isinstance(r, dict) and not r.get("duplicate")) == 1, res
    assert XPEvent.objects.filter(user=u, ref="lesson:race").count() == 1
    assert PlayerStats.objects.get(user=u).xp == 10
