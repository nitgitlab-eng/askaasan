import pytest
from django.core import mail

from apps.accounts.models import OneTimeToken

pytestmark = pytest.mark.django_db


def test_register_sends_verification_and_returns_tokens(client):
    res = client.post(
        "/api/users/register/", {"email": "A@Example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    assert res.status_code == 201
    assert {
        "access",
        "user",
    } <= res.data.keys() and "refresh" not in res.data  # refresh lives only in the cookie
    ck = res.cookies["aasan_refresh"]
    assert ck["httponly"] and ck["samesite"] == "Strict" and ck["path"] == "/api/users/"
    assert res.data["user"]["email"] == "a@example.com"
    assert res.data["user"]["preferences"]["mascot"]["character"] == "kili"
    assert len(mail.outbox) == 1


def test_register_rejects_duplicate_and_weak_password(client):
    client.post(
        "/api/users/register/", {"email": "a@example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    assert (
        client.post(
            "/api/users/register/", {"email": "a@example.com", "password": "Tamil#Learn2026"}, format="json"
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/users/register/", {"email": "b@example.com", "password": "123"}, format="json"
        ).status_code
        == 400
    )


def test_login_refresh_rotation_and_logout(client, auth):
    _, data = auth
    res = client.post(
        "/api/users/login/", {"email": "kavya@example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    assert res.status_code == 200
    assert (
        client.post(
            "/api/users/login/", {"email": "kavya@example.com", "password": "wrong"}, format="json"
        ).status_code
        == 401
    )

    old = res.cookies["aasan_refresh"].value
    new = client.post("/api/users/refresh-token/")  # the cookie is sent automatically
    assert new.status_code == 200 and "access" in new.data and "refresh" not in new.data
    assert new.cookies["aasan_refresh"].value != old
    # rotated token is blacklisted (also when presented the old way, in the body)
    fresh = type(client)()
    assert fresh.post("/api/users/refresh-token/", {"refresh": old}, format="json").status_code == 401
    out = client.post("/api/users/logout/")
    assert out.status_code == 204 and out.cookies["aasan_refresh"].value == ""
    assert client.post("/api/users/refresh-token/").status_code == 401


def test_email_verification_flow(client, auth):
    tok = OneTimeToken.objects.get(purpose="verify_email")
    assert (
        client.post("/api/users/email-verification/confirm/", {"token": tok.token}, format="json").status_code
        == 200
    )
    assert client.get("/api/users/me/").data["email_verified"] is True
    # single use
    assert (
        client.post("/api/users/email-verification/confirm/", {"token": tok.token}, format="json").status_code
        == 400
    )


def test_password_reset_does_not_leak_accounts(client, auth):
    assert (
        client.post(
            "/api/users/password-reset/request/", {"email": "nobody@example.com"}, format="json"
        ).status_code
        == 204
    )
    assert (
        client.post(
            "/api/users/password-reset/request/", {"email": "kavya@example.com"}, format="json"
        ).status_code
        == 204
    )
    tok = OneTimeToken.objects.get(purpose="reset_password")
    res = client.post(
        "/api/users/password-reset/confirm/",
        {"token": tok.token, "password": "Puthiya#Pass2026"},
        format="json",
    )
    assert res.status_code == 200
    assert (
        client.post(
            "/api/users/login/", {"email": "kavya@example.com", "password": "Puthiya#Pass2026"}, format="json"
        ).status_code
        == 200
    )


def test_preferences_patch_merges_and_validates(auth):
    client, _ = auth
    res = client.patch(
        "/api/users/preferences/",
        {"mascot": {"name": "Chitti", "outfit": "uniform"}, "appearance": {"theme": "kolam"}},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["mascot"]["name"] == "Chitti"
    assert res.data["mascot"]["character"] == "kili"  # untouched keys kept
    assert res.data["appearance"]["theme"] == "kolam"

    bad = client.patch(
        "/api/users/preferences/",
        {"appearance": {"theme": "neon"}, "mentor": {"reply_language": "klingon"}},
        format="json",
    )
    assert bad.status_code == 400
    assert "appearance.theme" in bad.data and "mentor.reply_language" in bad.data
    assert client.patch("/api/users/preferences/", {"hacker": True}, format="json").status_code == 400


def test_course_view_preference(auth):
    client, _ = auth
    # Default: the new map.
    assert client.get("/api/users/preferences/").data["learning"]["course_view"] == "map"
    res = client.patch("/api/users/preferences/", {"learning": {"course_view": "path"}}, format="json")
    assert res.status_code == 200 and res.data["learning"]["course_view"] == "path"
    assert res.data["learning"]["pace"] == "steady"  # other learning prefs untouched
    bad = client.patch("/api/users/preferences/", {"learning": {"course_view": "grid"}}, format="json")
    assert bad.status_code == 400


def test_profile_update(auth):
    client, _ = auth
    res = client.patch(
        "/api/users/profile/", {"display_name": "கவ்யா", "domain": "ai", "goals": ["ML job"]}, format="json"
    )
    assert res.status_code == 200
    assert res.data["profile"]["display_name"] == "கவ்யா"


def test_requires_auth(client, db):
    assert client.get("/api/users/me/").status_code == 401


def test_defaults_are_english_first(client):
    res = client.post(
        "/api/users/register/", {"email": "new@example.com", "password": "Tamil#Learn2026"}, format="json"
    )
    assert res.data["user"]["profile"]["language"] == "en"
    assert res.data["user"]["preferences"]["mentor"]["reply_language"] == "auto"


def test_v1_preferences_are_upgraded():
    from apps.accounts.preferences import upgrade

    old = {"version": 1, "mentor": {"language_mix": 1, "personality": "calm_guru"}}
    new = upgrade(old)
    assert new["version"] == 2
    assert new["mentor"]["reply_language"] == "tanglish"
    assert new["mentor"]["personality"] == "calm_guru"
    assert "language_mix" not in new["mentor"]


def test_v1_default_language_mix_becomes_auto():
    from apps.accounts.preferences import upgrade

    assert upgrade({"version": 1, "mentor": {"language_mix": 0}})["mentor"]["reply_language"] == "auto"
