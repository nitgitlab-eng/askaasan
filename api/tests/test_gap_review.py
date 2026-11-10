"""Technical gap review (Oct 2026): verifiable guardian consent, no behavioural nudges for minors, data retention,
the breached-password check, the readiness-probe cache and the live-voice call cap."""

import re
from datetime import timedelta

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User

pytestmark = pytest.mark.django_db
PW = "Tamil#Learn2026"


def _minor(email="kid@example.com", guardian="parent@example.com"):
    c = APIClient()
    r = c.post(
        "/api/users/register/",
        {
            "email": email,
            "password": PW,
            "accept_terms": True,
            "age_band": "minor",
            "guardian_email": guardian,
        },
        format="json",
    )
    assert r.status_code == 201, r.data
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
    return c, User.objects.get(email=email)


def _consent_token():
    msg = next(m for m in mail.outbox if "Please confirm" in m.subject)
    return re.search(r"/guardian/([^\s/]+)", msg.body).group(1)


def _upload(c):
    return c.post("/api/docs/", {"file": SimpleUploadedFile("n.txt", b"notes")}, format="multipart")


# ── Guardian consent ──


def test_a_minor_waits_for_the_guardian_and_the_guardian_unlocks():
    c, u = _minor()
    assert c.get("/api/users/me/").data["consent"]["guardian"] == "pending"
    r = _upload(c)
    assert r.status_code == 403 and r.data["code"] == "guardian_consent_required"
    token = _consent_token()
    assert APIClient().get(f"/api/guardian/{token}/").data["consent"] == "pending"
    assert (
        APIClient().post(f"/api/guardian/{token}/consent/", {"agree": True}, format="json").status_code == 200
    )
    u.refresh_from_db()
    assert u.guardian_consent_at and c.get("/api/users/me/").data["consent"]["guardian"] == "given"
    assert _upload(c).data.get("code") != "guardian_consent_required"


def test_a_guardian_who_objects_keeps_ai_locked_and_a_minor_cannot_untick_their_age():
    c, _ = _minor()
    token = _consent_token()
    APIClient().post(f"/api/guardian/{token}/consent/", {"agree": False}, format="json")
    assert c.get("/api/users/me/").data["consent"]["guardian"] == "objected"
    assert _upload(c).data["code"] == "guardian_consent_required"
    r = c.post("/api/legal/consent/", {"accept": True, "age_band": "adult"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "age_change_needs_support"


def test_a_new_guardian_must_confirm_afresh():
    c, u = _minor()
    APIClient().post(f"/api/guardian/{_consent_token()}/consent/", {"agree": True}, format="json")
    c.post(
        "/api/legal/consent/",
        {"accept": True, "age_band": "minor", "guardian_email": "other@example.com"},
        format="json",
    )
    u.refresh_from_db()
    assert u.guardian_consent_at is None and _upload(c).data["code"] == "guardian_consent_required"


def test_the_learner_can_resend_the_consent_email():
    c, _ = _minor()
    before = len(mail.outbox)
    r = c.post("/api/users/guardian/", {"action": "consent"}, format="json")
    assert r.status_code == 200 and len(mail.outbox) == before + 1


def test_adults_are_never_gated(auth):
    c, _ = auth
    assert c.get("/api/users/me/").data["consent"]["guardian"] is None
    from apps.orgs.extras import refusal

    assert refusal(User.objects.get(email="kavya@example.com"), "mentor") is None


def test_minors_are_gated_on_every_ai_feature_but_not_lessons():
    _, u = _minor()
    from apps.orgs.extras import refusal

    for feature in ("mentor", "roleplay", "live", "workshops", "docs", "voice"):
        assert refusal(u, feature) == "guardian_consent_required", feature
    assert refusal(u, "leaderboard") is None


# ── No behavioural nudges for minors ──


def test_winback_and_learned_times_skip_minors(monkeypatch):
    from apps.accounts import besttime, push, winback
    from apps.game.models import PlayerStats, XPEvent

    monkeypatch.setattr(push, "send", lambda *a, **k: None)
    _, kid = _minor()
    User.objects.filter(pk=kid.pk).update(email_verified=True)
    adult = User.objects.create_user("adult@example.com", PW, email_verified=True)
    for u in (kid, adult):
        PlayerStats.objects.create(user=u, last_active=timezone.localdate() - timedelta(days=3))
    mail.outbox.clear()
    assert winback.inactive()["inactive_3"] == 1
    assert [m.to for m in mail.outbox] == [[adult.email]]
    XPEvent.objects.create(user=kid, kind="lesson", xp=1, day=timezone.localdate())
    besttime.compute_all()
    from apps.accounts.models import ReminderState

    assert not ReminderState.objects.filter(user=kid).exclude(best_minute=None).exists()


# ── Retention ──


def test_retention_deletes_old_chats_and_keeps_recent(settings, auth):
    from apps.legal.tasks import apply_retention
    from apps.mentor.models import Conversation
    from apps.providers.models import LLMUsage

    user = User.objects.get(email="kavya@example.com")
    old, new = Conversation.objects.create(user=user), Conversation.objects.create(user=user)
    Conversation.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=400))
    LLMUsage.objects.create(task="grade", provider="fake", model="fake")
    LLMUsage.objects.filter().update(created_at=timezone.now() - timedelta(days=500))
    out = apply_retention()
    assert out["conversations"] == 1 and out["llm_usage"] == 1
    assert list(Conversation.objects.values_list("pk", flat=True)) == [new.pk]
    settings.MENTOR_RETENTION_DAYS = 0  # 0 keeps forever
    assert "conversations" not in apply_retention()


# ── Breached passwords ──


def test_breached_passwords_are_refused_and_an_outage_fails_open(settings, monkeypatch):
    import hashlib

    import httpx

    from apps.accounts import validators

    settings.PASSWORD_BREACH_CHECK = True
    pw = "Tamil#Learn2026"
    suffix = hashlib.sha1(pw.encode()).hexdigest().upper()[5:]

    class R:
        text = f"0000000000000000000000000000000000A:1\n{suffix}:42\n"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(httpx, "get", lambda url, **kw: R())
    r = APIClient().post("/api/users/register/", {"email": "b@example.com", "password": pw}, format="json")
    assert r.status_code == 400 and "breach" in str(r.data).lower()

    def down(url, **kw):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(httpx, "get", down)
    assert validators.breach_count(pw) == 0


# ── Readiness probe ──


def test_readiness_answers_are_reused_briefly(settings, monkeypatch):
    from config import health

    settings.HEALTH_CACHE_SECONDS = 30
    health._last = None
    calls = []
    monkeypatch.setattr(health, "CHECKS", {"db": lambda: calls.append(1)})
    for _ in range(5):
        assert APIClient().get("/api/health/ready/").status_code == 200
    assert len(calls) == 1
    health._last = None


# ── Live voice call cap ──


def test_live_voice_refuses_new_calls_when_the_host_is_full(settings, monkeypatch, auth):
    from apps.providers.voice import live

    c, _ = auth
    settings.VOICE_LIVE_MAX_CALLS = 2
    monkeypatch.setattr(live, "available", lambda: True)
    monkeypatch.setattr(live, "active_calls", lambda: 2)
    r = c.post("/api/voice/live/token/", {"feature": "mentor"}, format="json")
    assert r.status_code == 503 and r.data["code"] == "voice_busy" and r["Retry-After"] == "60"
    monkeypatch.setattr(live, "active_calls", lambda: None)  # LiveKit not answering: let the call try
    assert not live.calls_full(User.objects.get(email="kavya@example.com"))


def test_refresh_refuses_other_origins(auth, settings):
    c, _ = auth
    r = c.post("/api/users/refresh-token/", {}, format="json", HTTP_ORIGIN="https://evil.askaasan.com")
    assert r.status_code == 403
    r = c.post("/api/users/refresh-token/", {}, format="json", HTTP_ORIGIN=settings.FRONTEND_URL)
    assert r.status_code == 200
