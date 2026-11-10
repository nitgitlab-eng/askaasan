"""Hardening pass (agent HB): referrals, role-play end, review/Today scoping, checkpoint pre-test (H39 H41 H52 H53 H60)."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.game import services as game
from apps.game.models import PlayerStats, XPEvent
from apps.learning.models import Curriculum, Enrollment, Section, Subsection, UserSubsectionState
from apps.review.models import ReviewCard
from apps.study import today
from tests.test_study import _lesson

pytestmark = pytest.mark.django_db


def _client(email):
    u = User.objects.create_user(email, "Harden#2026pass")
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def _coins(u):
    return PlayerStats.objects.get(user=u).coins


# ── H39: referral coins wait for email verification, inviter capped ──


def test_referral_pays_only_after_verification_and_once(client):
    inviter = User.objects.create_user("inv-h39@x.in", "Harden#2026pass")
    code = game.stats_for(inviter).referral_code
    res = client.post(
        "/api/users/register/",
        {"email": "new-h39@x.in", "password": "Harden#2026pass", "ref": code},
        format="json",
    )
    assert res.status_code == 201
    new = User.objects.get(email="new-h39@x.in")
    assert PlayerStats.objects.get(user=new).referred_by_id == inviter.id
    assert _coins(inviter) == 0 and _coins(new) == 0  # nothing paid for an unverified signup
    assert game.pay_referral(new) is False

    new.email_verified = True
    new.save(update_fields=["email_verified"])
    assert game.pay_referral(new) is True
    assert _coins(inviter) >= 100 and _coins(new) == 100
    before = _coins(inviter)
    assert game.pay_referral(new) is False  # a second verification pays nothing
    assert _coins(inviter) == before and _coins(new) == 100


def test_verified_signup_is_paid_at_once_and_inviter_is_capped():
    inviter = User.objects.create_user("cap-h39@x.in", "Harden#2026pass")
    code = game.stats_for(inviter).referral_code
    day = timezone.localdate()
    XPEvent.objects.bulk_create(
        XPEvent(user=inviter, kind="referral", ref=f"invited:{9000 + i}", coins=100, day=day)
        for i in range(game.REFERRAL_CAP)
    )
    new = User.objects.create_user("g-h39@x.in", email_verified=True)  # e.g. a Google sign-up
    assert game.credit_referral(new, code) is True
    assert _coins(new) == 100  # the invited friend is still welcomed
    assert _coins(inviter) == 0  # but the inviter is past the cap
    assert not XPEvent.objects.filter(user=inviter, ref=f"invited:{new.id}").exists()


# ── H41: role-play end claims the session atomically ─────────────────


def test_roleplay_end_while_evaluating_is_409_and_does_not_evaluate(monkeypatch):
    from apps.roleplay import services as rp
    from apps.roleplay.models import RolePlaySession, RolePlayTurn, Scenario

    c, u = _client("rp-h41@x.in")
    sid = next(s["id"] for s in c.get("/api/roleplay/scenarios/").data if s["source"] == "library")
    s = RolePlaySession.objects.create(user=u, scenario=Scenario.objects.get(id=sid))
    for i in range(rp.MIN_TURNS_FOR_EVAL):
        RolePlayTurn.objects.create(session=s, role=RolePlayTurn.Role.LEARNER, text=f"turn {i}")
    RolePlaySession.objects.filter(pk=s.pk).update(status=RolePlaySession.Status.EVALUATING)
    called = []
    monkeypatch.setattr(rp, "finish", lambda *a, **k: called.append(1))
    r = c.post(f"/api/roleplay/sessions/{s.id}/end/")
    assert r.status_code == 409 and r.data["code"] == "evaluating"
    assert called == []


# ── H52: review sessions skip archived lessons ───────────────────────


def test_course_review_session_skips_archived_lessons():
    c, u = _client("rev-h52@x.in")
    cur, sub, acts = _lesson(u)
    sec2 = Section.objects.create(curriculum=cur, order=1, title="Old")
    old = Subsection.objects.create(section=sec2, order=0, title="Retired", archived=True)
    quiz = acts[0]
    quiz.pk = None
    quiz.subsection = old
    quiz.save()
    ReviewCard.objects.create(user=u, activity=quiz)  # a card that existed before the lesson was archived
    ids = set()
    for _ in range(5):
        r = c.get(f"/api/review/session/?mode=course&curriculum={cur.id}")
        assert r.status_code == 200
        ids |= {card["activity"]["id"] for card in r.data["cards"]}
    assert ids and quiz.id not in ids


# ── H53: Today only points at courses the learner can still open ─────


def test_today_ignores_courses_whose_access_ended():
    owner = User.objects.create_user("own-h53@x.in", "Harden#2026pass")
    cur, sub, acts = _lesson(owner)
    Curriculum.objects.filter(pk=cur.pk).update(published_at=timezone.now())
    c, u = _client("lr-h53@x.in")
    Enrollment.objects.create(user=u, curriculum=cur, access_until=timezone.now() - timedelta(days=1))
    UserSubsectionState.objects.create(user=u, subsection=sub, status="in_progress")
    ReviewCard.objects.create(user=u, activity=acts[0], due=timezone.now() - timedelta(days=1))
    assert today._review_station(u, "", 0) is None
    assert today._lesson_station(u) is None
    assert not any(s["key"].startswith("review") for s in c.get("/api/study/today/").data["stations"])

    Enrollment.objects.filter(user=u).update(access_until=timezone.now() + timedelta(days=1))
    assert today._review_station(u, "", 0)["n"] == 1  # control: same data, access open again
    assert today._lesson_station(u)["title"] == sub.title


# ── H60: the checkpoint pre-test never reveals the answer key ────────


def test_checkpoint_pre_hides_key_post_reveals(django_capture_on_commit_callbacks):
    c, u = _client("cp-h60@x.in")
    cur, _, _ = _lesson(u)
    with django_capture_on_commit_callbacks(execute=True):
        c.post(f"/api/study/courses/{cur.id}/checkpoint/")
    qs = c.get(f"/api/study/courses/{cur.id}/checkpoint/").data["questions"]
    answers = {q["id"]: 0 for q in qs}
    url = f"/api/study/courses/{cur.id}/checkpoint/submit/"
    pre = c.post(url, {"kind": "pre", "answers": answers}, format="json").data["review"]
    assert pre and all("correct" not in r and "explanation" not in r for r in pre)
    assert all("ok" in r and "picked" in r for r in pre)
    post = c.post(url, {"kind": "post", "answers": answers}, format="json").data["review"]
    assert all("correct" in r and "explanation" in r for r in post)


# ── Today on a fresh database: the built-in role-plays exist before anyone opens role-play ─────


def test_today_offers_a_roleplay_station_on_a_fresh_database():
    from apps.roleplay.models import Scenario

    Scenario.objects.filter(source="library").delete()
    c, _u = _client("lr-fresh@x.in")
    stations = c.get("/api/study/today/").data["stations"]
    assert any(s["kind"] == "roleplay" for s in stations)
    assert Scenario.objects.filter(source="library").exists()
