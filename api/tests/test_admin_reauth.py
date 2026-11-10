"""Admin console changes need a recent sign-in, so a stolen staff session alone can't alter the platform."""

import time

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import StaffRole, User
from apps.accounts.tokens import issue_tokens

pytestmark = pytest.mark.django_db
PW = "Admin#Reauth2026"
SITE = "/api/admin/site/"


@pytest.fixture(autouse=True)
def _reauth_on(settings):
    settings.ADMIN_REAUTH_MINUTES = 720


def _signed_in(*, hours_ago=0.0, strong=True):
    """A staff session whose last real sign-in was `hours_ago` (a refresh carries auth_time forward unchanged).
    `strong`: that sign-in was a passkey or an emailed code (staff admin changes need one, STAFF_SECOND_FACTOR)."""
    u = User.objects.create_user("boss@aasan.in", PW, is_staff=True, email_verified=True)
    StaffRole.objects.update_or_create(user=u, defaults={"roles": ["superadmin"]})
    c = APIClient()
    c.credentials(
        HTTP_AUTHORIZATION=f"Bearer {issue_tokens(u, auth_time=time.time() - hours_ago * 3600, strong=strong)['access']}"
    )
    return c


def test_a_recent_sign_in_can_change_settings():
    assert _signed_in(hours_ago=11).patch(SITE, {"legal_name": "Aasan"}, format="json").status_code == 200


def test_an_old_session_can_read_but_must_reauthenticate_to_change():
    c = _signed_in(hours_ago=13)
    r = c.patch(SITE, {"legal_name": "x"}, format="json")
    assert r.status_code == 403 and r.data["code"] == "reauth_required" and "email_code" in r.data["methods"]
    assert "password" not in r.data["methods"]  # staff: a second factor, not the password alone
    assert c.get(SITE).status_code == 200  # reading stays open


def test_a_password_alone_does_not_unlock_admin_changes():
    c = _signed_in(hours_ago=0, strong=False)  # signed in with a password just now
    r = c.patch(SITE, {"legal_name": "x"}, format="json")
    assert r.status_code == 403 and r.data["code"] == "reauth_required"


def test_emailed_code_reauth_unlocks_changes(mailoutbox):
    import re

    c = _signed_in(hours_ago=13)
    assert (
        c.post("/api/users/reauth/", {"password": PW}, format="json").status_code == 202
    )  # sends a code instead
    code = re.search(r"\b(\d{6})\b", mailoutbox[-1].body).group(1)
    fresh = c.post("/api/users/reauth/", {"code": code}, format="json")
    assert fresh.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh.data['access']}")
    assert c.patch(SITE, {"legal_name": "Aasan Learning"}, format="json").status_code == 200


def test_password_still_works_until_email_is_set_up(settings):
    """No passkey and no working email yet: the password counts, or nobody could configure mail."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"
    c = _signed_in(hours_ago=13, strong=False)
    fresh = c.post("/api/users/reauth/", {"password": PW}, format="json")
    assert fresh.status_code == 200
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {fresh.data['access']}")
    assert c.patch(SITE, {"legal_name": "Aasan Learning"}, format="json").status_code == 200


def test_off_when_set_to_zero(settings):
    settings.ADMIN_REAUTH_MINUTES = 0
    assert _signed_in(hours_ago=13).patch(SITE, {"legal_name": "x"}, format="json").status_code == 200


def test_security_events_are_logged_without_emails(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="aasan.security")
    User.objects.create_user("victim@aasan.in", PW)
    c = APIClient()
    for _ in range(10):
        c.post("/api/users/login/", {"email": "victim@aasan.in", "password": "wrong"}, format="json")
    sec = [r for r in caplog.records if r.name == "aasan.security"]
    events = [r.event for r in sec]
    assert events.count("password_failed") == 9 and events[-1] == "account_locked"
    assert all("victim" not in r.getMessage() and "victim" not in r.account for r in sec)
    assert len({r.account for r in sec}) == 1  # same account, grouped


def test_a_reserved_field_name_never_breaks_the_caller():
    from apps.accounts.security_log import security_event

    security_event("google_login", user_id=1, created=True, msg="x")


def test_reset_links_expire_after_an_hour():
    from apps.accounts.emails import send_password_reset
    from apps.accounts.models import OneTimeToken

    u = User.objects.create_user("forgot@aasan.in", PW)
    send_password_reset(u)
    from django.utils import timezone

    left = (OneTimeToken.objects.get(user=u).expires_at - timezone.now()).total_seconds()
    assert 3500 < left <= 3600
