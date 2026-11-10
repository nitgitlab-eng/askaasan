"""Live voice (LiveKit): availability, the join token and its agent dispatch, billing helpers, the agent's helpers."""

import asyncio
import json

import jwt
import pytest

from apps.accounts.models import User
from apps.providers.models import ProviderConfig, UsageCounter
from apps.providers.voice import agent, live

KEY = "sk_sarvam_live_test_1234"
LK_SECRET = "a" * 40


@pytest.fixture
def livekit(settings, monkeypatch):
    monkeypatch.setattr(live, "_server_up", lambda: True)
    settings.LIVEKIT_URL = "ws://livekit:7880"
    settings.LIVEKIT_PUBLIC_URL = "ws://localhost:8080/livekit"
    settings.LIVEKIT_API_KEY = "aasan"
    settings.LIVEKIT_API_SECRET = LK_SECRET
    settings.LIVEKIT_AGENT_NAME = "aasan-voice"
    return settings


def _sarvam(capability="tts", model="bulbul:v4-flash", key=KEY):
    row = ProviderConfig(capability=capability, provider="sarvam", model=model, voices={"ta": "kavitha"})
    row.set_key(key)
    row.save()
    return row


def test_off_without_livekit_or_sarvam(auth, settings, livekit, monkeypatch):
    client, _ = auth
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert client.get("/api/voice/config/").data["live"] is False  # no Sarvam key
    _sarvam()
    assert client.get("/api/voice/config/").data["live"] is True
    settings.LIVEKIT_API_SECRET = ""
    assert client.get("/api/voice/config/").data["live"] is False  # no LiveKit
    assert client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json").status_code == 503


def test_token_joins_one_room_and_dispatches_the_agent(auth, livekit):
    client, _ = auth
    _sarvam()
    res = client.post("/api/voice/live/token/", {"feature": "roleplay", "lang": "ta"}, format="json")
    assert res.status_code == 200
    body = res.data
    assert body["url"] == "ws://localhost:8080/livekit"
    claims = jwt.decode(body["token"], LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    user = User.objects.get(email="kavya@example.com")
    assert claims["sub"] == f"learner-{user.pk}"
    assert claims["video"]["room"] == body["room"] and claims["video"]["roomJoin"] is True
    dispatch = claims["roomConfig"]["agents"][0]
    assert dispatch["agentName"] == "aasan-voice"
    assert json.loads(dispatch["metadata"]) == {"user_id": user.pk, "lang": "ta", "feature": "roleplay"}
    assert KEY not in json.dumps(body)


def test_token_is_microphone_only(auth, livekit):
    client, _ = auth
    _sarvam()
    res = client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json")
    claims = jwt.decode(res.data["token"], LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert claims["video"]["canPublishSources"] == ["microphone"]


def test_a_new_call_ends_the_previous_one(auth, livekit, monkeypatch):
    client, _ = auth
    _sarvam()
    ended = []
    monkeypatch.setattr(live, "_end_room", ended.append)
    first = client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json").data["room"]
    assert ended == []
    second = client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json").data["room"]
    assert ended == [first] and second != first
    user = User.objects.get(email="kavya@example.com")
    live.call_ended(user.pk, first)  # the replaced call's agent leaving doesn't clear the newer call
    client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json")
    assert ended == [first, second]
    live.call_ended(
        user.pk, client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json").data["room"]
    )
    client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json")
    assert len(ended) == 3  # the last call had ended on its own: nothing more to close


def test_ending_a_room_calls_the_server_and_never_raises(livekit, monkeypatch):
    import httpx

    sent = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: sent.append((url, kw["json"])))
    live._end_room("voice-1-abc")
    assert sent == [("http://livekit:7880/twirp/livekit.RoomService/DeleteRoom", {"room": "voice-1-abc"})]

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", down)
    live._end_room("voice-1-abc")  # best effort


def test_call_length_cap(settings):
    settings.VOICE_LIVE_MAX_MINUTES = 30
    assert live.max_call_seconds() == 1800
    settings.VOICE_LIVE_MAX_MINUTES = 0
    assert live.max_call_seconds() == 60  # never below a minute


def test_token_refuses_unknown_feature_unknown_lang_falls_back(auth, livekit):
    client, _ = auth
    _sarvam()
    assert client.post("/api/voice/live/token/", {"feature": "nope"}, format="json").status_code == 400
    res = client.post("/api/voice/live/token/", {"feature": "mentor", "lang": "xx"}, format="json")
    claims = jwt.decode(res.data["token"], LK_SECRET, algorithms=["HS256"], options={"verify_aud": False})
    assert json.loads(claims["roomConfig"]["agents"][0]["metadata"])["lang"] == "en"


def test_token_needs_sign_in(client, db, livekit):
    _sarvam()
    assert client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json").status_code == 401


def test_token_refused_when_todays_voice_minutes_are_used(auth, livekit):
    client, _ = auth
    _sarvam()
    user = User.objects.get(email="kavya@example.com")
    assert live.charge_listening(user, 10 * 60, {}) is None  # the free plan's 10 minutes
    res = client.post("/api/voice/live/token/", {"feature": "mentor"}, format="json")
    assert res.status_code == 402


def test_live_voice_prefers_the_listening_row_and_known_models(db, livekit):
    _sarvam("tts", "bulbul:v4-flash")
    cfg = live.live_voice()
    assert cfg.key == KEY and cfg.stt_model == live.STT_MODEL and cfg.tts_model == "bulbul:v4-flash"
    _sarvam("stt", "saaras:v3", key="sk_other")
    cfg = live.live_voice()
    assert cfg.key == "sk_other" and cfg.stt_model == "saaras:v3" and cfg.tts_model == live.TTS_MODEL


def test_speaking_is_charged_and_stops_at_the_plan_limit(auth, livekit):
    _sarvam()
    user = User.objects.get(email="kavya@example.com")
    assert live.charge_speaking(user, 120, {}) is None
    assert UsageCounter.objects.get(user=user, metric="tts_chars").amount == 120
    assert live.charge_speaking(user, 10_000_000, {}) == "plan_limit"


def test_listening_refund(auth, livekit):
    _sarvam()
    user = User.objects.get(email="kavya@example.com")
    live.charge_listening(user, 15, {})
    live.refund_listening(user, 10)
    assert UsageCounter.objects.get(user=user, metric="stt_seconds").amount == 5


# ── The agent's helpers (the LiveKit session itself is exercised end to end, not here) ──


def test_turn_text_joins_finals_and_the_latest_interim():
    t = agent.TurnText()
    assert t.add("what is", False) == "what is"
    assert t.add("what is a prompt", True) == "what is a prompt"
    assert t.add("and an", False) == "what is a prompt and an"
    assert t.take() == "what is a prompt and an"
    assert t.text() == ""
    assert t.take("fallback words") == "fallback words"


def test_session_options_answer_fast_and_stop_on_speech():
    en, ta = agent.session_options("en"), agent.session_options("ta")
    assert (
        en["endpointing"]["min_delay"] < ta["endpointing"]["min_delay"]
    )  # Tamil has no turn model: a longer pause
    assert en["interruption"]["mode"] == "vad" and en["interruption"]["resume_false_interruption"] is True


def test_charged_stops_the_reply_at_the_limit():
    async def words():
        for w in ["Hello ", "", "there ", "friend."]:
            yield w

    paid, stopped = [], []

    async def pay(n):
        paid.append(n)
        return "plan_limit" if len(paid) == 2 else None

    async def on_limit(code):
        stopped.append(code)

    async def run():
        return [c async for c in agent.charged(words(), pay, on_limit)]

    assert asyncio.run(run()) == ["Hello "]
    assert paid == [6, 6] and stopped == ["plan_limit"]


def test_live_is_off_when_the_livekit_server_does_not_answer(auth, settings, monkeypatch):
    import httpx

    settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET = (
        "ws://livekit:7880",
        "devkey",
        "secret",
    )
    _sarvam()

    def down(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "get", down)
    client, _ = auth
    assert client.get("/api/voice/config/").data["live"] is False


def test_the_public_dev_key_pair_is_refused_on_a_public_site(auth, livekit):
    _sarvam()
    livekit.LIVEKIT_API_KEY, livekit.LIVEKIT_API_SECRET = "devkey", "secret"
    assert live.available() is True  # this machine (localhost): fine
    livekit.LIVEKIT_PUBLIC_URL = "wss://aasan.example/livekit"
    assert live.available() is False
    livekit.LIVEKIT_PUBLIC_URL = "ws://203.0.113.7:8080/livekit"  # plain ws:// on a public address too
    assert live.available() is False
    livekit.LIVEKIT_API_SECRET = "b" * 64
    assert live.available() is False  # the secret is fine but the key is still the public "devkey"
    livekit.LIVEKIT_API_KEY = "aasan"
    assert live.available() is True
    livekit.LIVEKIT_API_SECRET = "short-secret"
    assert live.available() is False
