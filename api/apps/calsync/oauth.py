"""OAuth 2.0 (authorization code + PKCE) and free/busy reads for Google Calendar and Microsoft Graph.
Read-only scopes only; nothing here ever writes to a learner's calendar. Tokens and secrets are never logged."""

import base64
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx
from django.conf import settings

GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar.freebusy"
MICROSOFT_SCOPES = "offline_access Calendars.Read"

SPEC = {
    "google": {
        "label": "Google Calendar",
        "scopes": GOOGLE_SCOPES,
        "console": "https://console.cloud.google.com/apis/credentials",
        "env": ("GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET"),
    },
    "microsoft": {
        "label": "Microsoft Outlook",
        "scopes": MICROSOFT_SCOPES,
        "console": "https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        "env": ("MICROSOFT_CALENDAR_CLIENT_ID", "MICROSOFT_CALENDAR_CLIENT_SECRET"),
    },
}


class CalendarError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code  # not_configured | reconnect | provider_error | network


@dataclass
class App:
    provider: str
    client_id: str
    secret: str
    tenant: str = "common"

    @property
    def redirect_uri(self) -> str:
        return redirect_uri(self.provider)


def redirect_uri(provider: str) -> str:
    """The exact URI the owner registers with Google / Microsoft (a page in the web app that finishes the connect)."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/calendar/callback/{provider}"


def app_for(provider: str) -> App | None:
    """Admin console first, then .env. None when the owner hasn't set it up (the UI then hides the button)."""
    from .models import CalendarApp

    if provider not in SPEC:
        return None
    row = CalendarApp.objects.filter(provider=provider).first()
    if row and not row.enabled:
        return None
    env_id, env_secret = SPEC[provider]["env"]
    client_id = (row.client_id if row else "") or os.environ.get(env_id, "")
    secret = (row.secret() if row and row.encrypted_secret else "") or os.environ.get(env_secret, "")
    if not (client_id and secret):
        return None
    return App(provider, client_id, secret, (row.tenant if row else "") or "common")


# ── PKCE ─────────────────────────────────────────────────────────────


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def _ms(app: App, path: str) -> str:
    return f"https://login.microsoftonline.com/{app.tenant}/oauth2/v2.0/{path}"


def authorize_url(app: App, state: str, challenge: str) -> str:
    if app.provider == "google":
        q = {
            "client_id": app.client_id,
            "redirect_uri": app.redirect_uri,
            "response_type": "code",
            "scope": GOOGLE_SCOPES,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(q)
    q = {
        "client_id": app.client_id,
        "redirect_uri": app.redirect_uri,
        "response_type": "code",
        "response_mode": "query",
        "scope": MICROSOFT_SCOPES,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return _ms(app, "authorize") + "?" + urlencode(q)


# ── HTTP ─────────────────────────────────────────────────────────────


def _request(method: str, url: str, **kw) -> httpx.Response:
    try:
        return httpx.request(method, url, timeout=20, **kw)
    except httpx.HTTPError as e:
        raise CalendarError("network", type(e).__name__) from e


def _token_call(app: App, data: dict) -> dict:
    url = "https://oauth2.googleapis.com/token" if app.provider == "google" else _ms(app, "token")
    r = _request("POST", url, data={"client_id": app.client_id, "client_secret": app.secret, **data})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 400:
        # invalid_grant = the learner revoked access or the token expired → they must reconnect.
        err = str(body.get("error") or "")
        raise CalendarError(
            "reconnect"
            if err in ("invalid_grant", "interaction_required", "consent_required")
            else "provider_error",
            err[:60],
        )
    return body


def exchange_code(app: App, code: str, verifier: str) -> dict:
    """Returns {"refresh_token", "access_token", "scope"}."""
    body = _token_call(
        app,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": app.redirect_uri,
            "code_verifier": verifier,
        },
    )
    if not body.get("refresh_token"):
        raise CalendarError("provider_error", "no_refresh_token")
    return body


def refresh(app: App, refresh_token: str) -> dict:
    body = _token_call(app, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    if not body.get("access_token"):
        raise CalendarError("provider_error", "no_access_token")
    return body  # Microsoft rotates refresh tokens: caller stores body["refresh_token"] when present


def revoke(app: App, refresh_token: str) -> None:
    """Google supports revoking; Microsoft has no per-app token revoke with these scopes (we delete our copy)."""
    if app.provider == "google":
        try:
            _request(
                "POST",
                "https://oauth2.googleapis.com/revoke",
                data={"token": refresh_token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except CalendarError:
            pass


def _iso(d: datetime) -> str:
    return d.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    if "." in s:  # Graph sends 7 fractional digits; Python takes 6
        head, _, tail = s.partition(".")
        frac = "".join(ch for ch in tail if ch.isdigit())
        tz = tail[len(frac) :]
        s = f"{head}.{frac[:6]}{tz}"
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def busy(app: App, access_token: str, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Busy intervals (aware datetimes) between start and end on the learner's primary calendar."""
    auth = {"Authorization": f"Bearer {access_token}"}
    if app.provider == "google":
        r = _request(
            "POST",
            "https://www.googleapis.com/calendar/v3/freeBusy",
            headers=auth,
            json={"timeMin": _iso(start), "timeMax": _iso(end), "items": [{"id": "primary"}]},
        )
        if r.status_code == 401:
            raise CalendarError("reconnect", "unauthorized")
        if r.status_code >= 400:
            raise CalendarError("provider_error", f"freebusy {r.status_code}")
        cal = (r.json().get("calendars") or {}).get("primary") or {}
        return [
            (_parse(b["start"]), _parse(b["end"]))
            for b in cal.get("busy", [])
            if b.get("start") and b.get("end")
        ]
    out: list[tuple[datetime, datetime]] = []
    url = "https://graph.microsoft.com/v1.0/me/calendarView"
    params: dict | None = {
        "startDateTime": _iso(start),
        "endDateTime": _iso(end),
        "$select": "start,end,showAs,isCancelled",
        "$top": "200",
    }
    for _ in range(5):  # at most 1000 events in 14 days
        r = _request("GET", url, headers={**auth, "Prefer": 'outlook.timezone="UTC"'}, params=params)
        if r.status_code == 401:
            raise CalendarError("reconnect", "unauthorized")
        if r.status_code >= 400:
            raise CalendarError("provider_error", f"calendarView {r.status_code}")
        data = r.json()
        for ev in data.get("value", []):
            if ev.get("isCancelled") or ev.get("showAs") in ("free", "workingElsewhere"):
                continue
            s, e = (ev.get("start") or {}).get("dateTime"), (ev.get("end") or {}).get("dateTime")
            if s and e:
                out.append((_parse(s), _parse(e)))
        url, params = data.get("@odata.nextLink"), None
        if not url or not url.startswith("https://graph.microsoft.com/"):
            break
    return out
