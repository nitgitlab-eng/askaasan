"""Regression tests for the accounts/auth fix pass (register R16, R40, R43, R55-R57; security S1-S3, S7-S9, S16, S22)."""

from datetime import UTC, datetime, timedelta

import pytest
from django.core.cache import cache, caches
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import OneTimeToken, User
from apps.extension.models import ExtensionPairing, ExtensionToken, token_hash

pytestmark = pytest.mark.django_db
PW = "Fix#Accounts2026"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


# ── Password reset (R40, S1) ─────────────────────────────────────────


def test_weak_password_on_reset_is_400_not_500():
    u = User.objects.create_user("weak@example.test", PW)
    tok = OneTimeToken.issue(u, OneTimeToken.Purpose.RESET_PASSWORD)
    r = APIClient().post(
        "/api/users/password-reset/confirm/", {"token": tok.token, "password": "123"}, format="json"
    )
    assert r.status_code == 400 and r.data["detail"] == "weak_password" and r.data["password"]
    tok.refresh_from_db()
    assert tok.used_at is None  # the link still works for a second, stronger try


def test_password_reset_revokes_refresh_and_extension_tokens():
    u = User.objects.create_user("victim@example.test", PW)
    login = APIClient().post("/api/users/login/", {"email": u.email, "password": PW}, format="json")
    old_refresh = login.cookies["aasan_refresh"].value
    raw = "ext-raw-token-for-test"
    ExtensionToken.objects.create(user=u, token_hash=token_hash(raw), name="Chrome")
    tok = OneTimeToken.issue(u, OneTimeToken.Purpose.RESET_PASSWORD)
    r = APIClient().post(
        "/api/users/password-reset/confirm/",
        {"token": tok.token, "password": "New#Strong2026pw"},
        format="json",
    )
    assert r.status_code == 200
    attacker = APIClient()
    attacker.cookies["aasan_refresh"] = old_refresh
    assert attacker.post("/api/users/refresh-token/").status_code == 401
    ext = APIClient()
    ext.credentials(HTTP_AUTHORIZATION=f"AasanExt {raw}")
    assert ext.get("/api/ext/tasks/").status_code == 401
    # The session issued by the reset itself still works.
    fresh = APIClient()
    fresh.cookies["aasan_refresh"] = r.cookies["aasan_refresh"].value
    assert fresh.post("/api/users/refresh-token/").status_code == 200


# ── Google sign-in (S2, R43) ─────────────────────────────────────────


@pytest.fixture
def google(settings, monkeypatch):
    from google.oauth2 import id_token

    settings.GOOGLE_CLIENT_ID = "test-client"
    info = {"sub": "g-1", "email": "victim@example.test", "email_verified": True, "name": "V"}
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: dict(info))
    return info


def test_google_does_not_link_to_unverified_local_account(google):
    reg = APIClient().post(
        "/api/users/register/",
        {"email": "victim@example.test", "password": PW, "accept_terms": True, "age_band": "adult"},
        format="json",
    )
    assert reg.status_code == 201
    r = APIClient().post("/api/users/google/", {"credential": "x"}, format="json")
    assert r.status_code == 409 and r.data["detail"] == "account_unverified"
    assert User.objects.get(email="victim@example.test").google_sub is None


def test_google_links_to_verified_local_account(google):
    u = User.objects.create_user("victim@example.test", PW)
    u.email_verified = True
    u.save()
    r = APIClient().post("/api/users/google/", {"credential": "x"}, format="json")
    assert r.status_code == 200 and r.data["created"] is False and r.data["user"]["id"] == u.id


def test_google_signup_language_is_validated(google):
    r = APIClient().post("/api/users/google/", {"credential": "x", "language": "x" * 500}, format="json")
    assert r.status_code == 200 and r.data["created"] is True
    assert User.objects.get(email="victim@example.test").profile.language == "en"
    google.update(sub="g-2", email="other@example.test")
    APIClient().post("/api/users/google/", {"credential": "x", "language": "ta"}, format="json")
    assert User.objects.get(email="other@example.test").profile.language == "ta"


# ── Mail caps (S3) ───────────────────────────────────────────────────


def test_verification_resend_is_capped(mailoutbox):
    c, u = client_for("victim@example.test")
    codes = [c.post("/api/users/email-verification/request/").status_code for _ in range(8)]
    assert codes[:5] == [204] * 5 and set(codes[5:]) == {429}
    assert len(mailoutbox) == 5


def test_guardian_consent_email_is_capped(mailoutbox):
    c, u = client_for("kid@example.test")
    codes = [
        c.post(
            "/api/legal/consent/",
            {"accept": True, "age_band": "minor", "guardian_email": f"g{i}@example.test"},
            format="json",
        ).status_code
        for i in range(6)
    ]
    assert codes[:3] == [200] * 3 and set(codes[3:]) == {429}
    assert len(mailoutbox) == 3
    # Re-accepting with the same guardian sends nothing and is never capped.
    same = User.objects.get(id=u.id).guardian_email
    assert (
        c.post(
            "/api/legal/consent/",
            {"accept": True, "age_band": "minor", "guardian_email": same},
            format="json",
        ).status_code
        == 200
    )


# ── Archive account (S7) ─────────────────────────────────────────────


def test_archive_and_invalid_emails_cannot_register():
    for email in ("archive@aasan.invalid", "ARCHIVE@aasan.invalid", "x@anything.invalid"):
        r = APIClient().post("/api/users/register/", {"email": email, "password": PW}, format="json")
        assert r.status_code == 400 and "email_reserved" in str(r.data)


def test_archive_user_neutralises_a_loginable_row():
    from apps.legal.api import _archive_user

    squat = User.objects.create_user("archive@aasan.invalid", PW)
    raw = "archive-ext-token"
    ExtensionToken.objects.create(user=squat, token_hash=token_hash(raw))
    u = _archive_user()
    assert u.id == squat.id and not u.is_active and not u.has_usable_password()
    assert not ExtensionToken.objects.filter(user=u, revoked_at__isnull=True).exists()
    assert (
        APIClient()
        .post("/api/users/login/", {"email": squat.email, "password": PW}, format="json")
        .status_code
        == 401
    )


# ── SMTP password retarget (S8) ──────────────────────────────────────


def test_smtp_password_cleared_when_destination_changes():
    from apps.legal.models import MailConfig

    staff, _ = client_for("ops@example.test", is_staff=True)
    staff.patch(
        "/api/admin/mail/",
        {
            "host": "smtp.example.test",
            "username": "u",
            "password": "dummy-pass-1234",
            "from_email": "noreply@example.test",
        },
        format="json",
    )
    staff.patch(
        "/api/admin/mail/", {"host": "smtp.example.test", "from_name": "Aasan"}, format="json"
    )  # same host: kept
    assert MailConfig.objects.get(pk=1).encrypted_password
    r = staff.patch(
        "/api/admin/mail/", {"host": "127.0.0.1", "port": 1025, "security": "none"}, format="json"
    )
    assert r.data["password"] is None and MailConfig.objects.get(pk=1).encrypted_password == ""
    staff.patch(
        "/api/admin/mail/", {"username": "v", "password": "new-pass-5678"}, format="json"
    )  # new password supplied
    assert MailConfig.objects.get(pk=1).password() == "new-pass-5678"


# ── Delete-account step-up lockout (S9) ──────────────────────────────


def test_delete_account_password_guessing_is_locked_out():
    c, u = client_for("victim@example.test")
    codes = [
        c.post(
            "/api/legal/delete-account/", {"confirm": "DELETE", "password": f"wrong-{i}"}, format="json"
        ).status_code
        for i in range(5)
    ]
    assert codes == [403] * 5
    r = c.post("/api/legal/delete-account/", {"confirm": "DELETE", "password": PW}, format="json")
    assert r.status_code == 429 and r.data["code"] == "too_many_attempts"
    assert User.objects.filter(id=u.id).exists()


# ── Django admin login lockout (S16) ─────────────────────────────────


def test_django_admin_login_shares_account_lockout():
    User.objects.create_user("staff@example.test", PW, is_staff=True)
    c = Client()
    for i in range(10):
        r = c.post("/api/django-admin/login/", {"username": "staff@example.test", "password": f"wrong-{i}"})
        assert r.status_code == 200
    r = c.post("/api/django-admin/login/", {"username": "staff@example.test", "password": PW})
    assert r.status_code == 429
    assert (
        APIClient()
        .post("/api/users/login/", {"email": "staff@example.test", "password": PW}, format="json")
        .status_code
        == 429
    )
    cache.clear()  # the LRU cache can be evicted or restarted; the lockout must survive that
    assert (
        Client()
        .post("/api/django-admin/login/", {"username": "staff@example.test", "password": PW})
        .status_code
        == 429
    )
    caches["security"].clear()  # the lockout window ending
    assert (
        Client()
        .post("/api/django-admin/login/", {"username": "staff@example.test", "password": PW})
        .status_code
        == 302
    )


# ── Extension pairing guesses (S22) ──────────────────────────────────


def test_global_failed_claim_budget_pauses_claims_but_keeps_codes():
    from apps.extension.api import CLAIM_FAIL_BUDGET

    c, _ = client_for("learner@example.test")
    code = c.post("/api/ext/pair/start/").data["code"]
    wrong = [f"{n:06d}" for n in range(1000000) if f"{n:06d}" != code][:CLAIM_FAIL_BUDGET]
    for i, guess in enumerate(wrong):  # a different /64 every time: the per-IP throttle never fires
        r = APIClient().post(
            "/api/ext/pair/claim/", {"code": guess}, format="json", REMOTE_ADDR=f"2001:db8:{i + 1:x}::1"
        )
        assert r.status_code == 400
    # Claims pause (even the right code isn't checked) instead of wiping every learner's live code (S22 re-check).
    assert APIClient().post("/api/ext/pair/claim/", {"code": code}, format="json").status_code == 429
    assert ExtensionPairing.objects.filter(code=code, expires_at__gt=timezone.now()).exists()
    cache.clear()  # the window passes
    caches["security"].clear()
    assert APIClient().post("/api/ext/pair/claim/", {"code": code}, format="json").status_code == 200


# ── Guardian (R16, R55, R56, R57) ────────────────────────────────────


def _minor(email="teen@example.test"):
    c, u = client_for(email, age_band="minor", guardian_email="amma@example.test")
    User.objects.filter(id=u.id).update(date_joined=timezone.now() - timedelta(days=30))
    return c, User.objects.get(id=u.id)


def test_guardian_digest_catches_up_after_missed_sunday(mailoutbox):
    from apps.accounts.guardian import send_weekly

    _minor()
    today = timezone.localdate()
    sunday = today + timedelta(days=(6 - today.weekday()) % 7)
    monday = timezone.make_aware(
        datetime.combine(sunday + timedelta(days=1), datetime.min.time()).replace(hour=9)
    )
    assert send_weekly(monday) == 1  # Sunday's run never happened
    assert send_weekly(monday + timedelta(days=1)) == 0  # once per week
    assert send_weekly(monday + timedelta(days=6)) == 1  # next Sunday, back on schedule
    assert "on 0 days" in mailoutbox[0].body and "day(s)" not in mailoutbox[0].body


def test_guardian_view_dates_are_ist():
    from apps.accounts.guardian import summary
    from apps.learning.models import Curriculum, Section, Subsection, UserSubsectionState

    _, u = _minor()
    cur = Curriculum.objects.create(owner=u, goal="g", title="Course")
    sub = Subsection.objects.create(
        section=Section.objects.create(curriculum=cur, order=0, title="S"), order=0, title="L", objective="o"
    )
    # 20:00 UTC yesterday is 01:30 IST today.
    utc = datetime.combine(timezone.localdate() - timedelta(days=1), datetime.min.time()).replace(
        hour=20, tzinfo=UTC
    )
    UserSubsectionState.objects.create(user=u, subsection=sub, status="completed", completed_at=utc)
    assert summary(u, 7)["lessons"][0]["on"] == timezone.localdate(utc) == utc.date() + timedelta(days=1)


def test_guardian_digest_toggle_parses_false_string():
    c, u = _minor()
    assert c.patch("/api/users/guardian/", {"digest": "false"}, format="json").data["digest"] is False
    assert c.patch("/api/users/guardian/", {"digest": "true"}, format="json").data["digest"] is True
    assert c.patch("/api/users/guardian/", {"digest": "maybe"}, format="json").status_code == 400


# ── Connect guest lesson: plan check and record under one lock (billing follow-up) ──


def test_connect_guest_lesson_plan_check_holds_user_lock(monkeypatch):
    from django.db import connection

    from apps.billing import services as billing
    from apps.billing.models import UsageEvent
    from apps.connect.tools import Ctx, ToolError, create_guest_lesson

    _, u = client_for("admin@example.test")
    seen = []
    monkeypatch.setattr(billing, "lock_user", lambda user: seen.append(connection.in_atomic_block))

    def full(user, key, adding=1):
        assert seen == [True]  # the check runs after the row lock, inside the same transaction
        raise billing.PlanLimit(key, 20, 20, "free")

    monkeypatch.setattr(billing, "check", full)
    with pytest.raises(ToolError) as e:
        create_guest_lesson(Ctx(user=u, org=None, grant=None), {"topic": "Saving money"})
    assert e.value.code == "plan_limit" and not UsageEvent.objects.filter(user=u).exists()


# ── Sign-in config for the page ──────────────────────────────────────


def test_auth_config_exposes_only_the_google_client_id(settings):
    settings.GOOGLE_CLIENT_ID = "123-abc.apps.googleusercontent.com"
    r = APIClient().get("/api/users/auth-config/")  # no Authorization header: the login page is signed out
    assert r.status_code == 200 and r.data == {
        "google_client_id": "123-abc.apps.googleusercontent.com",
        "sso": False,
    }


def test_auth_config_is_empty_when_google_is_not_set_up(settings):
    settings.GOOGLE_CLIENT_ID = ""
    r = APIClient().get("/api/users/auth-config/")
    assert r.status_code == 200 and r.data == {"google_client_id": "", "sso": False}


def test_signed_out_resend_mails_only_an_unverified_account(mailoutbox):
    User.objects.create_user("pending@example.test", PW)
    v = User.objects.create_user("done@example.test", PW)
    v.email_verified = True
    v.save()

    def post(email):
        return APIClient().post("/api/users/email-verification/request/", {"email": email}, format="json")

    assert post("pending@example.test").status_code == 204 and len(mailoutbox) == 1
    assert mailoutbox[0].to == ["pending@example.test"]
    # Verified or unknown addresses answer the same 204 and send nothing (no account enumeration).
    assert post("done@example.test").status_code == 204 and post("nobody@example.test").status_code == 204
    assert post("").status_code == 204
    assert len(mailoutbox) == 1
    # The per-recipient daily cap still holds, silently.
    codes = [post("pending@example.test").status_code for _ in range(6)]
    assert set(codes) == {204} and len(mailoutbox) == 5
