"""Calendar connect (Google / Outlook, read-only): admin setup, OAuth + PKCE with a signed user-bound state,
encrypted refresh tokens, disconnect, and re-planning study blocks into real gaps. All provider HTTP is mocked."""

import base64
import hashlib
import json
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.calsync import oauth
from apps.calsync.models import CalendarApp, CalendarConnection
from apps.calsync.services import busy_by_day, find_slot
from apps.providers import crypto
from apps.study.models import StudyBlock

pytestmark = pytest.mark.django_db


def client_for(email, staff=False):
    u = User.objects.create_user(email, "Cal#2026passwd", is_staff=staff)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


@pytest.fixture
def http(monkeypatch):
    """Records every outgoing call; answers token, revoke, Google freeBusy and Graph calendarView."""
    state = {"calls": [], "busy": [], "token_error": None}

    def request(method, url, **kw):
        state["calls"].append({"method": method, "url": url, **kw})
        if url.endswith("/token"):
            if state["token_error"]:
                return Resp(400, {"error": state["token_error"]})
            grant = kw["data"]["grant_type"]
            return Resp(
                200,
                {
                    "access_token": "at_1",
                    "refresh_token": "rt_secret_1" if grant == "authorization_code" else "rt_rotated",
                    "scope": "calendar",
                },
            )
        if "revoke" in url:
            return Resp(200, {})
        if "freeBusy" in url:
            return Resp(
                200, {"calendars": {"primary": {"busy": [{"start": s, "end": e} for s, e in state["busy"]]}}}
            )
        if "calendarView" in url:
            return Resp(
                200,
                {
                    "value": [
                        {
                            "start": {"dateTime": s + ".0000000"},
                            "end": {"dateTime": e + ".0000000"},
                            "showAs": "busy",
                        }
                        for s, e in state["busy"]
                    ]
                    + [
                        {
                            "start": {"dateTime": "2030-01-01T00:00:00"},
                            "end": {"dateTime": "2030-01-02T00:00:00"},
                            "showAs": "free",
                        }
                    ]
                },
            )
        return Resp(404, {})

    monkeypatch.setattr(oauth.httpx, "request", request)
    return state


@pytest.fixture
def google():
    CalendarApp.objects.create(
        provider="google",
        client_id="123-abc.apps.googleusercontent.com",
        encrypted_secret=crypto.encrypt("gsecret_XYZ"),
    )


@pytest.fixture
def microsoft():
    CalendarApp.objects.create(
        provider="microsoft", client_id="0000-1111", encrypted_secret=crypto.encrypt("msecret_XYZ")
    )


def connect(c, provider="google"):
    r = c.post(f"/api/calendar/{provider}/connect/")
    assert r.status_code == 200, r.data
    q = parse_qs(urlparse(r.data["url"]).query)
    return q


def finish(c, q, provider="google", code="authcode"):
    return c.post(
        f"/api/calendar/{provider}/callback/", {"code": code, "state": q["state"][0]}, format="json"
    )


# ── Not configured ──────────────────────────────────────────────────


def test_not_configured_is_visible_and_harmless():
    c, _ = client_for("a@x.in")
    r = c.get("/api/calendar/")
    assert r.status_code == 200 and r.data["read_only"] is True
    assert {p["provider"]: p["configured"] for p in r.data["providers"]} == {
        "google": False,
        "microsoft": False,
    }
    assert c.post("/api/calendar/google/connect/").status_code == 503
    assert c.post("/api/calendar/replan/").data["code"] == "not_connected"
    assert c.post("/api/calendar/yahoo/connect/").status_code == 404


def test_disabled_app_counts_as_not_configured(google):
    CalendarApp.objects.filter(provider="google").update(enabled=False)
    c, _ = client_for("a@x.in")
    assert c.post("/api/calendar/google/connect/").status_code == 503


# ── OAuth ───────────────────────────────────────────────────────────


def test_google_connect_uses_pkce_readonly_scope_and_encrypts_token(google, http):
    c, u = client_for("a@x.in")
    q = connect(c)
    assert (
        q["scope"] == [oauth.GOOGLE_SCOPES]
        and q["code_challenge_method"] == ["S256"]
        and q["access_type"] == ["offline"]
    )
    assert q["redirect_uri"] == ["http://localhost:5173/calendar/callback/google"]
    r = finish(c, q)
    assert r.status_code == 200 and r.data["providers"][0]["connected"] is True
    assert "rt_secret_1" not in json.dumps(r.data, default=str)
    token_call = http["calls"][0]
    verifier = token_call["data"]["code_verifier"]
    assert (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        == q["code_challenge"][0]
    )
    conn = CalendarConnection.objects.get(user=u)
    assert conn.encrypted_refresh_token != "rt_secret_1" and conn.token() == "rt_secret_1"


def test_microsoft_scopes(microsoft, http):
    c, _ = client_for("a@x.in")
    q = connect(c, "microsoft")
    assert set(q["scope"][0].split()) == {"offline_access", "Calendars.Read"}
    assert finish(c, q, "microsoft").status_code == 200
    assert "login.microsoftonline.com/common/" in http["calls"][0]["url"]


def test_state_is_bound_to_user_and_single_use(google, http):
    a, _ = client_for("a@x.in")
    b, ub = client_for("b@x.in")
    q = connect(a)
    assert finish(b, q).data["code"] == "bad_state"  # someone else's state
    assert finish(a, q, provider="microsoft").status_code in (400, 503)
    assert finish(a, q).status_code == 200
    assert finish(a, q).data["code"] == "bad_state"  # replay
    assert not CalendarConnection.objects.filter(user=ub).exists()
    assert (
        a.post("/api/calendar/google/callback/", {"code": "x", "state": "forged"}, format="json").data["code"]
        == "bad_state"
    )


def test_expired_state_rejected(google, http, monkeypatch):
    c, _ = client_for("a@x.in")
    q = connect(c)
    monkeypatch.setattr("apps.calsync.api.STATE_MAX_AGE", -1)
    assert finish(c, q).data["code"] == "bad_state"


def test_failed_exchange_stores_nothing(google, http):
    http["token_error"] = "invalid_grant"
    c, u = client_for("a@x.in")
    r = finish(c, connect(c))
    assert r.status_code == 502 and not CalendarConnection.objects.filter(user=u).exists()


def test_disconnect_revokes_and_deletes(google, http):
    c, u = client_for("a@x.in")
    finish(c, connect(c))
    r = c.delete("/api/calendar/google/")
    assert r.status_code == 200 and not CalendarConnection.objects.filter(user=u).exists()
    assert any("revoke" in x["url"] and x["data"]["token"] == "rt_secret_1" for x in http["calls"])
    assert c.delete("/api/calendar/google/").status_code == 404


# ── Re-plan ─────────────────────────────────────────────────────────


def test_find_slot_prefers_preferred_time_then_nearest():
    assert find_slot([], 20, [19 * 60]) == 19 * 60
    busy = [(18 * 60 + 50, 20 * 60 + 10)]  # meeting 19:00–20:00 with buffer
    assert find_slot(busy, 20, [19 * 60]) == 18 * 60 + 30  # nearest free time that fits (just before)
    assert (
        find_slot(busy, 60, [19 * 60]) == 20 * 60 + 15
    )  # too long to fit before → just after, on the 15-min grid
    assert find_slot([(6 * 60, 22 * 60)], 20, [19 * 60]) is None
    assert find_slot([(15 * 60, 22 * 60)], 30, [19 * 60]) == 14 * 60 + 30
    assert find_slot([], 30, [7 * 60], earliest=9 * 60) == 9 * 60


def test_busy_by_day_splits_overnight_events():
    tz = timezone.get_current_timezone()
    s = datetime(2030, 5, 1, 23, 0, tzinfo=tz)
    out = busy_by_day([(s, s + timedelta(hours=2))])
    assert out[date(2030, 5, 1)] == [(23 * 60 - 10, 24 * 60)] and out[date(2030, 5, 2)] == [(0, 60 + 10)]


def _prefs(u, times=("19:00",), days=(0, 1, 2, 3, 4, 5, 6)):
    p = u.preferences
    data = dict(p.data)
    data["learning"] = {
        **data.get("learning", {}),
        "reminder_times": list(times),
        "study_days": list(days),
        "daily_goal_minutes": 20,
    }
    p.data = data
    p.save()


def test_replan_moves_blocks_around_meetings(google, http, monkeypatch):
    c, u = client_for("a@x.in")
    _prefs(u)
    finish(c, connect(c))
    tomorrow = timezone.localdate() + timedelta(days=1)
    # tomorrow 18:30–20:30 local is busy
    tz = timezone.get_current_timezone()
    s = datetime.combine(tomorrow, datetime.min.time()).replace(hour=18, minute=30, tzinfo=tz)
    http["busy"] = [
        (
            (s).astimezone(oauth.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            (s + timedelta(hours=2)).astimezone(oauth.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    ]
    custom = StudyBlock.objects.create(
        user=u, date=tomorrow, start="21:00", minutes=30, kind="custom", title="Mine", auto=False
    )
    r = c.post("/api/calendar/replan/")
    assert r.status_code == 200 and r.data["busy"] == 1 and r.data["moved"] >= 1
    day = list(StudyBlock.objects.filter(user=u, date=tomorrow, auto=True).order_by("start"))
    starts = [b.start for b in day]
    assert all(not ("18:20" <= st < "20:40") for st in starts)  # outside the meeting + buffer
    assert starts == sorted(starts) and day[0].start < "18:20" or day[0].start >= "20:40"
    custom.refresh_from_db()
    assert custom.start == "21:00"  # learner-made blocks never move
    # the other days keep the preferred time
    later = (
        StudyBlock.objects.filter(user=u, date=tomorrow + timedelta(days=2), auto=True)
        .order_by("start")
        .first()
    )
    assert later.start == "19:00"
    # read-only: no write calls to the calendar APIs
    assert not [
        x for x in http["calls"] if "googleapis.com/calendar" in x["url"] and "freeBusy" not in x["url"]
    ]
    conn = CalendarConnection.objects.get(user=u)
    assert conn.last_synced_at is not None


def test_replan_flags_reconnect_when_access_revoked(google, http):
    c, u = client_for("a@x.in")
    _prefs(u)
    finish(c, connect(c))
    http["token_error"] = "invalid_grant"
    r = c.post("/api/calendar/replan/")
    assert r.status_code == 200 and r.data["needs_reconnect"] == ["google"]
    assert r.data["providers"][0]["needs_reconnect"] is True


def test_microsoft_rotated_refresh_token_is_saved(microsoft, http):
    c, u = client_for("a@x.in")
    _prefs(u)
    finish(c, connect(c, "microsoft"), "microsoft")
    assert c.post("/api/calendar/replan/").status_code == 200
    assert CalendarConnection.objects.get(user=u).token() == "rt_rotated"


# ── Admin ───────────────────────────────────────────────────────────


def test_admin_sets_keys_masked_and_shows_redirects():
    staff, _ = client_for("admin@x.in", staff=True)
    r = staff.get("/api/admin/calendar-apps/")
    assert r.status_code == 200
    uris = {a["provider"]: a["redirect_uri"] for a in r.data["apps"]}
    assert uris == {
        "google": "http://localhost:5173/calendar/callback/google",
        "microsoft": "http://localhost:5173/calendar/callback/microsoft",
    }
    r = staff.patch(
        "/api/admin/calendar-apps/google/",
        {"client_id": "123-abc.apps.googleusercontent.com", "client_secret": "GOCSPX-supersecret99"},
        format="json",
    )
    assert r.status_code == 200 and r.data["ready"] is True and r.data["secret"] == "••••et99"
    assert "supersecret" not in json.dumps(r.data, default=str)
    assert CalendarApp.objects.get(provider="google").encrypted_secret != "GOCSPX-supersecret99"
    # changing the client id drops the old secret
    r = staff.patch(
        "/api/admin/calendar-apps/google/", {"client_id": "other.apps.googleusercontent.com"}, format="json"
    )
    assert r.data["secret"] is None and r.data["ready"] is False
    assert (
        staff.patch(
            "/api/admin/calendar-apps/google/", {"client_id": "bad id <script>"}, format="json"
        ).status_code
        == 400
    )
    assert staff.patch("/api/admin/calendar-apps/yahoo/", {}, format="json").status_code == 404


def test_admin_endpoints_staff_only():
    c, _ = client_for("a@x.in")
    assert c.get("/api/admin/calendar-apps/").status_code == 403
    assert c.patch("/api/admin/calendar-apps/google/", {"client_id": "x"}, format="json").status_code == 403
    assert APIClient().get("/api/calendar/").status_code == 401
