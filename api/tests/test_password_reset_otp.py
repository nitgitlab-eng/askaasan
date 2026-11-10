"""Forgot password with an emailed 6-digit code: request → verify-otp (code → reset token) → confirm (new password)."""

import re

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User

pytestmark = pytest.mark.django_db

PW = "Reset#Otp2026"
NEW_PW = "Puthiya#Otp2026"


def _code(mailoutbox) -> str:
    return re.search(r"reset code is (\d{6})", mailoutbox[-1].body).group(1)


def _request(email):
    return APIClient().post("/api/users/password-reset/request/", {"email": email}, format="json")


def _verify(email, code):
    return APIClient().post(
        "/api/users/password-reset/verify-otp/", {"email": email, "code": code}, format="json"
    )


def test_code_resets_password_and_signs_in(mailoutbox):
    User.objects.create_user("otp@aasan.in", PW)
    assert _request("otp@aasan.in").status_code == 204
    mail = mailoutbox[-1]
    assert mail.alternatives and "text/html" in mail.alternatives[0][1]  # the styled HTML version
    res = _verify("OTP@aasan.in", _code(mailoutbox))
    assert res.status_code == 200
    res = APIClient().post(
        "/api/users/password-reset/confirm/", {"token": res.data["token"], "password": NEW_PW}, format="json"
    )
    assert res.status_code == 200 and res.data["access"]
    login = APIClient().post("/api/users/login/", {"email": "otp@aasan.in", "password": NEW_PW}, format="json")
    assert login.status_code == 200


def test_code_works_once(mailoutbox):
    User.objects.create_user("once@aasan.in", PW)
    _request("once@aasan.in")
    code = _code(mailoutbox)
    assert _verify("once@aasan.in", code).status_code == 200
    assert _verify("once@aasan.in", code).data["detail"] == "wrong_code"


def test_wrong_codes_lock_the_code(mailoutbox):
    User.objects.create_user("guess@aasan.in", PW)
    _request("guess@aasan.in")
    code = _code(mailoutbox)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert _verify("guess@aasan.in", wrong).data["detail"] == "wrong_code"
    res = _verify("guess@aasan.in", wrong)
    assert res.status_code == 429 and res.data["detail"] == "otp_locked"
    assert _verify("guess@aasan.in", code).status_code == 400  # the real code is gone too


def test_new_mail_replaces_old_code(mailoutbox):
    User.objects.create_user("again@aasan.in", PW)
    _request("again@aasan.in")
    old = _code(mailoutbox)
    _request("again@aasan.in")
    new = _code(mailoutbox)
    if old != new:
        assert _verify("again@aasan.in", old).status_code == 400
    assert _verify("again@aasan.in", new).status_code == 200


def test_unknown_email_looks_like_wrong_code():
    res = _verify("nobody@aasan.in", "123456")
    assert res.status_code == 400 and res.data["detail"] == "wrong_code"
