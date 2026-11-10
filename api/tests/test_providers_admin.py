import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.accounts.models import User
from apps.providers.models import ProviderConfig

pytestmark = pytest.mark.django_db
SECRET = "sk-super-secret-value-1234"


@pytest.fixture
def staff(client):
    user = User.objects.create_user("admin@aasan.test", "Admin#Pass2026", is_staff=True)
    client.force_authenticate(user)
    return client


def test_non_staff_forbidden(auth):
    client, _ = auth
    assert client.get("/api/admin/providers/").status_code == 403
    assert client.patch("/api/admin/providers/tts/", {"provider": "openai"}, format="json").status_code == 403


def test_save_key_is_encrypted_and_never_returned(staff):
    res = staff.patch(
        "/api/admin/providers/tts/",
        {"provider": "openai", "api_key": SECRET, "voices": {"ta": "coral"}},
        format="json",
    )
    assert res.status_code == 200
    assert res.data["key"] == {
        "needed": True,
        "set": True,
        "from": "admin",
        "masked": "••••1234",
        "env_var": "OPENAI_API_KEY",
    }
    assert SECRET not in str(res.data)
    row = ProviderConfig.objects.get(capability="tts")
    assert SECRET not in row.encrypted_key and row.get_key() == SECRET
    listing = staff.get("/api/admin/providers/")
    assert SECRET not in str(listing.data)


def test_switching_provider_drops_old_key(staff):
    staff.patch("/api/admin/providers/stt/", {"provider": "openai", "api_key": SECRET}, format="json")
    res = staff.patch("/api/admin/providers/stt/", {"provider": "sarvam"}, format="json")
    assert res.data["key"]["from"] is None and res.data["model"] == "saarika:v2.5"


def test_rejects_unknown_provider_and_limits(staff):
    assert staff.patch("/api/admin/providers/tts/", {"provider": "acme"}, format="json").status_code == 400
    assert staff.patch("/api/admin/providers/tts/", {"limits": {"hack": 1}}, format="json").status_code == 400
    assert staff.patch("/api/admin/providers/nope/", {}, format="json").status_code == 404


def test_blank_key_clears(staff):
    staff.patch("/api/admin/providers/tts/", {"provider": "openai", "api_key": SECRET}, format="json")
    res = staff.patch("/api/admin/providers/tts/", {"api_key": ""}, format="json")
    assert res.data["key"]["from"] in (None, "env")


def test_test_endpoint_missing_key(staff, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    staff.patch("/api/admin/providers/tts/", {"provider": "sarvam"}, format="json")
    res = staff.post("/api/admin/providers/tts/test/", {}, format="json")
    assert res.status_code == 400 and res.data["code"] == "missing_key"


# ── learner voice endpoints (fake adapter) ───────────────────────────


@pytest.fixture
def fake_voice(db):
    for cap in ("stt", "tts"):
        ProviderConfig.objects.create(
            capability=cap,
            provider="fake",
            model="x",
            limits={"stt_seconds_per_day": 10, "tts_chars_per_day": 50},
        )


def test_voice_config_defaults_to_browser(auth):
    client, _ = auth
    res = client.get("/api/voice/config/")
    assert res.data["stt"]["engine"] == "browser" and res.data["tts"]["engine"] == "browser"


def test_speak_and_budget(auth, fake_voice, monkeypatch):
    import apps.providers.voice_api as v

    monkeypatch.setattr(v, "needs_key", lambda *a: False)
    client, _ = auth
    res = client.post("/api/voice/speak/", {"text": "வணக்கம் Kavya!"}, format="json")
    assert res.status_code == 200 and res["Content-Type"] == "audio/wav" and res.content[:4] == b"RIFF"
    over = client.post("/api/voice/speak/", {"text": "x" * 60}, format="json")
    assert over.status_code == 429 and over.data["code"] == "voice_budget_exceeded"


def test_voice_config_reports_browser_when_key_missing(auth, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    ProviderConfig.objects.create(capability="tts", provider="sarvam", model="bulbul:v2")
    client, _ = auth
    res = client.get("/api/voice/config/")
    assert res.data["tts"] == {"engine": "browser", "provider": "sarvam"}


def test_speak_failure_does_not_charge_budget(auth, fake_voice, monkeypatch):
    import apps.providers.voice_api as v
    from apps.providers.models import UsageCounter
    from apps.providers.voice.adapters import VoiceError

    monkeypatch.setattr(v, "needs_key", lambda *a: False)

    def boom(*a):
        raise VoiceError("provider_error")

    monkeypatch.setattr(v, "synthesize", boom)
    client, _ = auth
    res = client.post("/api/voice/speak/", {"text": "x" * 40}, format="json")
    assert res.status_code == 502
    assert sum(u.amount for u in UsageCounter.objects.filter(metric="tts_chars")) == 0


def test_transcribe(auth, fake_voice, monkeypatch):
    import apps.providers.voice_api as v

    monkeypatch.setattr(v, "needs_key", lambda *a: False)
    client, _ = auth
    clip = SimpleUploadedFile("a.webm", b"\x1aE\xdf\xa3" + b"0" * 100, content_type="audio/webm")
    res = client.post("/api/voice/transcribe/", {"audio": clip, "seconds": "3"}, format="multipart")
    assert res.status_code == 200 and res.data["text"] == "test transcript"
    clip2 = SimpleUploadedFile("b.webm", b"0" * 100, content_type="audio/webm")
    assert (
        client.post(
            "/api/voice/transcribe/", {"audio": clip2, "seconds": "9"}, format="multipart"
        ).status_code
        == 429
    )
