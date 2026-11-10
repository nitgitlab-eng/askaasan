"""Deepgram as a voice provider: Nova speech-to-text (en-IN and Tamil) and Aura text-to-speech (English only).
No real calls: httpx.post is replaced, and the request it would have sent is checked."""

from types import SimpleNamespace

import httpx
import pytest

from apps.providers.catalog import CAPABILITIES, ENV_KEYS
from apps.providers.models import ProviderConfig
from apps.providers.voice import adapters
from apps.providers.voice.adapters import VoiceError

KEY = "dg-test-key-0000"


def cfg(model="", voices=None):
    return SimpleNamespace(provider="deepgram", key=KEY, model=model, voices=voices or {})


class Recorder:
    def __init__(self, response):
        self.response, self.calls = response, []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        return self.response


def resp(status=200, *, json=None, content=b""):
    req = httpx.Request("POST", "https://api.deepgram.com/")
    if json is not None:
        return httpx.Response(status, json=json, request=req)
    return httpx.Response(status, content=content, request=req)


def test_catalog_offers_deepgram_for_listening_and_speaking():
    assert CAPABILITIES["stt"]["providers"]["deepgram"]["default_model"] == "nova-3"
    tts = CAPABILITIES["tts"]["providers"]["deepgram"]
    assert tts["voices"]["en"] and tts["voices"]["ta"] == []  # Aura has no Tamil voice
    assert all(v.startswith("aura-2-") and v.endswith("-en") for v in tts["voices"]["en"])
    assert ENV_KEYS["deepgram"] == "DEEPGRAM_API_KEY"


def test_transcribe_sends_raw_audio_with_token_auth_and_parses_the_transcript(monkeypatch):
    body = {"results": {"channels": [{"alternatives": [{"transcript": " AI learns from examples. "}]}]}}
    rec = Recorder(resp(json=body))
    monkeypatch.setattr(adapters.httpx, "post", rec)
    out = adapters.transcribe(cfg(model="nova-3"), b"webm-bytes", "audio/webm;codecs=opus", "en")
    assert out == "AI learns from examples."
    url, kw = rec.calls[0]
    assert url == "https://api.deepgram.com/v1/listen"
    assert kw["headers"]["Authorization"] == f"Token {KEY}"
    assert kw["headers"]["Content-Type"] == "audio/webm;codecs=opus"
    assert kw["params"] == {"model": "nova-3", "smart_format": "true", "language": "en-IN"}
    assert kw["content"] == b"webm-bytes"


def test_transcribe_tamil_uses_nova3_tamil(monkeypatch):
    rec = Recorder(resp(json={"results": {"channels": [{"alternatives": [{"transcript": "வணக்கம்"}]}]}}))
    monkeypatch.setattr(adapters.httpx, "post", rec)
    assert adapters.transcribe(cfg(), b"x", "audio/webm", "ta") == "வணக்கம்"
    assert rec.calls[0][1]["params"]["language"] == "ta" and rec.calls[0][1]["params"]["model"] == "nova-3"


def test_transcribe_handles_an_empty_result(monkeypatch):
    monkeypatch.setattr(adapters.httpx, "post", Recorder(resp(json={"results": {"channels": []}})))
    assert adapters.transcribe(cfg(), b"x", "audio/webm", "en") == ""


def test_speak_english_uses_the_chosen_aura_voice_as_mp3(monkeypatch):
    rec = Recorder(resp(content=b"ID3mp3-bytes"))
    monkeypatch.setattr(adapters.httpx, "post", rec)
    audio, mime = adapters.synthesize(cfg(voices={"en": "aura-2-helena-en"}), "Hello Priya!", "en")
    assert (audio, mime) == (b"ID3mp3-bytes", "audio/mpeg")
    url, kw = rec.calls[0]
    assert url == "https://api.deepgram.com/v1/speak"
    assert kw["params"] == {"model": "aura-2-helena-en", "encoding": "mp3"}
    assert kw["json"] == {"text": "Hello Priya!"} and kw["headers"]["Authorization"] == f"Token {KEY}"


def test_speak_defaults_to_thalia(monkeypatch):
    rec = Recorder(resp(content=b"mp3"))
    monkeypatch.setattr(adapters.httpx, "post", rec)
    adapters.synthesize(cfg(), "Hi", "en")
    assert rec.calls[0][1]["params"]["model"] == "aura-2-thalia-en"


def test_speak_tamil_is_refused_without_calling_deepgram(monkeypatch):
    rec = Recorder(resp(content=b"mp3"))
    monkeypatch.setattr(adapters.httpx, "post", rec)
    with pytest.raises(VoiceError) as e:
        adapters.synthesize(cfg(), "வணக்கம்", "ta")
    assert e.value.code == "unsupported_language" and rec.calls == []


@pytest.mark.parametrize(
    ("status", "code"),
    [(401, "invalid_key"), (403, "invalid_key"), (429, "rate_limited"), (500, "provider_error")],
)
def test_errors_map_to_voice_codes(monkeypatch, status, code):
    monkeypatch.setattr(adapters.httpx, "post", Recorder(resp(status, json={"err_msg": "nope"})))
    with pytest.raises(VoiceError) as e:
        adapters.synthesize(cfg(), "Hi", "en")
    assert e.value.code == code
    with pytest.raises(VoiceError) as e:
        adapters.transcribe(cfg(), b"x", "audio/webm", "en")
    assert e.value.code == code


@pytest.mark.django_db
def test_tamil_line_answers_422_and_refunds_so_the_browser_reads_it(auth, monkeypatch):
    import apps.providers.voice_api as v
    from apps.providers.models import UsageCounter

    monkeypatch.setenv("DEEPGRAM_API_KEY", KEY)
    ProviderConfig.objects.create(capability="tts", provider="deepgram", model="aura-2")
    monkeypatch.setattr(v, "synthesize", adapters.synthesize)
    client, _ = auth
    res = client.post("/api/voice/speak/", {"text": "வணக்கம் Kavya!"}, format="json")
    assert res.status_code == 422 and res.data["code"] == "unsupported_language"
    assert sum(u.amount for u in UsageCounter.objects.filter(metric="tts_chars")) == 0


@pytest.mark.django_db
def test_voice_config_uses_the_server_with_a_deepgram_key_and_the_browser_without(auth, monkeypatch):
    ProviderConfig.objects.create(capability="stt", provider="deepgram", model="nova-3")
    client, _ = auth
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    no_key = {"engine": "browser", "provider": "deepgram", "streaming": False}
    assert client.get("/api/voice/config/").data["stt"] == no_key
    monkeypatch.setenv("DEEPGRAM_API_KEY", KEY)
    keyed = {"engine": "server", "provider": "deepgram", "streaming": True}  # live conversation too
    assert client.get("/api/voice/config/").data["stt"] == keyed


@pytest.mark.django_db
def test_admin_can_choose_deepgram_and_test_it(client, monkeypatch):
    from apps.accounts.models import User

    staff = User.objects.create_user("admin@aasan.test", "Admin#Pass2026", is_staff=True)
    client.force_authenticate(staff)
    res = client.patch("/api/admin/providers/tts/", {"provider": "deepgram", "api_key": KEY}, format="json")
    assert (
        res.status_code == 200
        and res.data["model"] == "aura-2"
        and res.data["key"]["env_var"] == "DEEPGRAM_API_KEY"
    )
    assert KEY not in str(res.data)
    monkeypatch.setattr(adapters.httpx, "post", Recorder(resp(content=b"ID3mp3")))
    test = client.post("/api/admin/providers/tts/test/", {"lang": "en"}, format="json")
    assert test.status_code == 200 and test["Content-Type"] == "audio/mpeg" and test.content == b"ID3mp3"
