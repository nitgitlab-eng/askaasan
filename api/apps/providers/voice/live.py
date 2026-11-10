"""Live voice over LiveKit: a WebRTC room per voice conversation, with Aasan's voice agent (`run_voice_agent`) in it.

The agent is the voice only (listening, end-of-turn detection, speaking, stopping when the learner talks). The words
still come from each feature's own socket in the browser (mentor, role-play, live class, workshop), so plan limits,
saved chats and feature logic are unchanged: the browser hands the agent each reply to speak, and the agent hands the
browser each finished turn.

Billing: listening is charged like streamed listening (voice minutes, prepaid in blocks of session time), speaking like
read-aloud (characters), both against the Sarvam row's daily limits.
"""

import json
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from ..services import BudgetExceeded, Resolved, charge, resolve
from .stream import _charge_block, _refund

STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v4-flash"
LANGS = {"en": "en-IN", "ta": "ta-IN"}
TOKEN_TTL = timedelta(minutes=10)  # time to join; the room itself lives as long as the call
BLOCK_SECONDS = 15.0  # listening prepaid this far ahead


@dataclass
class LiveVoice:
    """What the agent needs from the admin's provider settings."""

    key: str
    stt_model: str
    tts_model: str
    voices: dict
    limits: dict


def _sarvam_row() -> Resolved | None:
    """The Sarvam provider row with a key: Listening first, then Speaking: Tamil, then Speaking."""
    for cap in ("stt", "tts_ta", "tts"):
        cfg = resolve(cap)
        if cfg.provider == "sarvam" and cfg.enabled and cfg.key:
            return cfg
    return None


def live_voice() -> LiveVoice | None:
    """None when live voice can't run: LiveKit isn't set up, or there is no Sarvam key."""
    if not (settings.LIVEKIT_URL and settings.LIVEKIT_API_KEY and settings.LIVEKIT_API_SECRET):
        return None
    cfg = _sarvam_row()
    if not cfg:
        return None
    stt_model = cfg.model if cfg.capability == "stt" and cfg.model.startswith("saaras") else STT_MODEL
    tts_model = cfg.model if cfg.capability != "stt" and cfg.model.startswith("bulbul") else TTS_MODEL
    return LiveVoice(
        key=cfg.key, stt_model=stt_model, tts_model=tts_model, voices=cfg.voices, limits=cfg.limits
    )


def _http_url() -> str:
    return settings.LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")


def max_call_seconds() -> float:
    return max(60.0, float(settings.VOICE_LIVE_MAX_MINUTES) * 60)


def _active_key(user_pk) -> str:
    return f"live-call:{user_pk}"


def _end_room(room: str) -> None:
    """Close a call's room on the server (best effort): its agent leaves and stops charging."""
    import httpx
    from livekit import api

    token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_grants(
        api.VideoGrants(room_create=True)
    )
    try:
        httpx.post(
            f"{_http_url()}/twirp/livekit.RoomService/DeleteRoom",
            json={"room": room},
            headers={"Authorization": f"Bearer {token.to_jwt()}"},
            timeout=2.0,
        )
    except httpx.HTTPError:
        pass


def active_calls() -> int | None:
    """Voice calls open on the LiveKit server right now (None when it can't be asked)."""
    import httpx
    from livekit import api

    token = api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET).with_grants(
        api.VideoGrants(room_list=True)
    )
    try:
        r = httpx.post(
            f"{_http_url()}/twirp/livekit.RoomService/ListRooms",
            json={},
            headers={"Authorization": f"Bearer {token.to_jwt()}"},
            timeout=2.0,
        )
        r.raise_for_status()
        rooms = r.json().get("rooms") or []
    except (httpx.HTTPError, ValueError):
        return None
    return sum(1 for room in rooms if str(room.get("name", "")).startswith("voice-"))


def calls_full(user) -> bool:
    """Each call holds 200–400 MB in the voice agent, so a host takes VOICE_LIVE_MAX_CALLS at once (0 = no cap).
    A learner replacing their own call doesn't count twice. Unknown (server not answering) lets the call try."""
    from django.core.cache import cache

    cap = settings.VOICE_LIVE_MAX_CALLS
    if not cap:
        return False
    n = active_calls()
    if n is None:
        return False
    return n - (1 if cache.get(_active_key(user.pk)) else 0) >= cap


def call_ended(user_pk, room: str) -> None:
    """The agent's call is over: it no longer counts as this learner's active call (unless a newer one replaced it)."""
    from django.core.cache import cache

    if cache.get(_active_key(user_pk)) == room:
        cache.delete(_active_key(user_pk))


def _server_up() -> bool:
    """The LiveKit server answers (checked at most every 30 s): a stack started without it falls back at once
    instead of every voice screen waiting for an agent that never comes."""
    from django.core.cache import cache

    up = cache.get("livekit-up")
    if up is None:
        import httpx

        try:
            up = httpx.get(_http_url(), timeout=1.0).status_code < 500
        except httpx.HTTPError:
            up = False
        cache.set("livekit-up", up, 30)
    return up


def dev_keys_in_production() -> bool:
    """LiveKit's public dev pair (or a short secret) on a public site: anyone could mint tokens, so voice stays off.

    Production settings refuse to start in this state (config/hardening.py); this is the second layer."""
    from config.hardening import is_local_url, weak_livekit_keys

    return not is_local_url(settings.LIVEKIT_PUBLIC_URL) and weak_livekit_keys(
        settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET
    )


def available() -> bool:
    if dev_keys_in_production():
        import logging

        logging.getLogger(__name__).error(
            "live voice off: set LIVEKIT_API_KEY/SECRET (the dev pair is public)"
        )
        return False
    return live_voice() is not None and _server_up()


def issue_token(user, lang: str, feature: str) -> dict:
    """A one-room join token for this learner, with Aasan's voice agent dispatched into the same room.

    One call per learner: a new call ends the previous one (a reload or a second tab), so calls can't be stacked to
    burn through voice minutes or our Sarvam budget in parallel."""
    from django.core.cache import cache
    from livekit import api

    room = f"voice-{user.pk}-{secrets.token_hex(6)}"
    if old := cache.get(_active_key(user.pk)):
        _end_room(old)
    cache.set(_active_key(user.pk), room, int(max_call_seconds() + TOKEN_TTL.total_seconds()))
    meta = json.dumps({"user_id": user.pk, "lang": lang if lang in LANGS else "en", "feature": feature})
    token = (
        api.AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(f"learner-{user.pk}")
        .with_name("learner")
        .with_ttl(TOKEN_TTL)
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=room,
                can_publish=True,
                can_publish_sources=["microphone"],  # a voice call: no camera or screen tracks
                can_subscribe=True,
            )
        )
        .with_room_config(
            api.RoomConfiguration(
                agents=[api.RoomAgentDispatch(agent_name=settings.LIVEKIT_AGENT_NAME, metadata=meta)]
            )
        )
        .to_jwt()
    )
    return {"url": settings.LIVEKIT_PUBLIC_URL, "token": token, "room": room}


def charge_listening(user, seconds: float, limits: dict) -> dict | None:
    """Prepay `seconds` of listening: None, or the error (plan limit / budget) that ends the call."""
    return _charge_block(user, seconds, limits.get("stt_seconds_per_day", 0))


def refund_listening(user, seconds: float):
    _refund(user, seconds)


def charge_speaking(user, chars: int, limits: dict) -> str | None:
    """Charge a line Aasan is about to say: None, or the error code (nothing is said)."""
    from apps.billing.services import PlanLimit, check, lock_user

    with transaction.atomic():
        lock_user(user)
        try:
            check(user, "tts_chars_per_day", chars)
        except PlanLimit:
            return "plan_limit"
        try:
            charge(user, "tts_chars", chars, limits.get("tts_chars_per_day", 0))
        except BudgetExceeded:
            return "voice_budget_exceeded"
    return None
