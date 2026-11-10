"""Lesson media (podcast, explainer, Listen): admin switches (off by default), the shared speech-clip cache, Tamil
routed to its own voice, and two different podcast host voices. No real provider calls: httpx.post is replaced."""

import base64
from io import StringIO

import httpx
import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.accounts.models import AdminAuditLog, StaffRole, User
from apps.providers import clips
from apps.providers.models import PlatformSettings, ProviderConfig, SpeechClip, UsageCounter
from apps.providers.services import resolve
from apps.providers.voice import adapters
from tests.test_study import _lesson, client_for

pytestmark = pytest.mark.django_db
DG, SV = "dg-test-key-0000", "sv-test-key-0000"
MP3 = b"ID3fake-mp3-audio"


class FakeHttp:
    """Stands in for httpx.post: records each call and answers like Deepgram (mp3 bytes) or Sarvam (base64 wav)."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url, kw))
        req = httpx.Request("POST", url)
        if "sarvam" in url:
            wav = adapters._beep_wav(0.1)
            return httpx.Response(200, json={"audios": [base64.b64encode(wav).decode()]}, request=req)
        return httpx.Response(200, content=MP3, request=req)


@pytest.fixture
def http(monkeypatch, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    fake = FakeHttp()
    monkeypatch.setattr(adapters.httpx, "post", fake)
    monkeypatch.setenv("DEEPGRAM_API_KEY", DG)
    monkeypatch.setenv("SARVAM_API_KEY", SV)
    return fake


def english_deepgram(**voices):
    return ProviderConfig.objects.create(capability="tts", provider="deepgram", model="aura-2", voices=voices)


def tamil_sarvam(**voices):
    return ProviderConfig.objects.create(
        capability="tts_ta", provider="sarvam", model="bulbul:v4-flash", voices=voices
    )


def tts_chars(user) -> float:
    return sum(u.amount for u in UsageCounter.objects.filter(user=user, metric="tts_chars"))


# ── switches ─────────────────────────────────────────────────────────


def test_lesson_media_is_off_by_default_and_every_endpoint_refuses():
    c, u = client_for("off@x.in")
    _, sub, _ = _lesson(u)
    assert c.get("/api/users/me/").data["features"] == {"podcast": False, "explainer": False, "listen": False}
    for res in (
        c.get(f"/api/study/lessons/{sub.id}/podcast/"),
        c.post(f"/api/study/lessons/{sub.id}/podcast/", {}, format="json"),
        c.get(f"/api/study/lessons/{sub.id}/explainer/"),
        c.post(f"/api/study/lessons/{sub.id}/explainer/", {}, format="json"),
        c.post(f"/api/study/lessons/{sub.id}/listened/", {"kind": "listen", "parts": [0]}, format="json"),
        c.post(f"/api/study/lessons/{sub.id}/listened/", {"kind": "podcast", "parts": [0]}, format="json"),
    ):
        assert res.status_code == 403 and res.data["code"] == "feature_off"


@pytest.mark.parametrize("feature", ["podcast", "explainer", "listen"])
def test_each_switch_turns_on_only_its_own_feature(feature):
    PlatformSettings.objects.create(pk=1, **{f"{feature}_enabled": True})
    c, u = client_for(f"{feature}@x.in")
    _, sub, _ = _lesson(u)
    assert c.get("/api/users/me/").data["features"] == {
        f: f == feature for f in ("podcast", "explainer", "listen")
    }
    podcast = c.get(f"/api/study/lessons/{sub.id}/podcast/")
    explainer = c.get(f"/api/study/lessons/{sub.id}/explainer/")
    listen = c.post(f"/api/study/lessons/{sub.id}/listened/", {"kind": "listen", "parts": [0]}, format="json")
    got = {"podcast": podcast, "explainer": explainer, "listen": listen}
    for f, res in got.items():
        if f == feature:
            assert res.status_code == 200
        else:
            assert res.status_code == 403 and res.data["code"] == "feature_off"


# ── admin switches: staff only, by role, audited ─────────────────────


def staff_client(email, roles=None):
    u = User.objects.create_user(email, "Admin#Media2026", is_staff=True)
    if roles is not None:
        StaffRole.objects.update_or_create(user=u, defaults={"roles": roles})
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def test_admin_features_are_staff_only_by_role_and_audited():
    learner, _ = client_for("learner@x.in")
    assert learner.get("/api/admin/features/").status_code == 403
    assert learner.patch("/api/admin/features/", {"podcast": True}, format="json").status_code == 403
    finance, _ = staff_client("fin@x.in", ["finance"])
    assert finance.patch("/api/admin/features/", {"podcast": True}, format="json").status_code == 403
    assert not PlatformSettings.load().podcast_enabled

    content, staff = staff_client("content@x.in", ["content"])
    assert content.get("/api/admin/features/").data["podcast"] is False
    res = content.patch("/api/admin/features/", {"podcast": True, "listen": True}, format="json")
    assert res.status_code == 200
    assert (res.data["podcast"], res.data["explainer"], res.data["listen"]) == (True, False, True)
    s = PlatformSettings.load()
    assert s.podcast_enabled and s.listen_enabled and not s.explainer_enabled and s.updated_by == staff
    log = AdminAuditLog.objects.get(path="/api/admin/features/")
    assert log.actor == staff and log.section == "features" and log.data == {"podcast": True, "listen": True}
    assert content.patch("/api/admin/features/", {"podcast": "maybe"}, format="json").status_code == 400


def test_admin_can_save_host_voices_and_set_up_tamil_speaking(monkeypatch):
    c, _ = staff_client("root@x.in")
    res = c.patch(
        "/api/admin/providers/tts/",
        {"provider": "deepgram", "voices": {"en_host_a": "aura-2-luna-en", "en_host_b": "aura-2-orion-en"}},
        format="json",
    )
    assert res.status_code == 200 and res.data["voices"]["en_host_b"] == "aura-2-orion-en"
    bad = c.patch("/api/admin/providers/tts/", {"voices": {"xx": "a"}}, format="json")
    assert bad.status_code == 400
    ta = c.patch("/api/admin/providers/tts_ta/", {"provider": "sarvam", "api_key": SV}, format="json")
    assert (
        ta.status_code == 200
        and ta.data["label"] == "Speaking: Tamil"
        and ta.data["model"] == "bulbul:v4-flash"
    )
    listing = c.get("/api/admin/providers/").data
    assert "tts_ta" in listing["catalog"] and any(x["capability"] == "tts_ta" for x in listing["configs"])


# ── clip cache ───────────────────────────────────────────────────────


def test_identical_clip_is_generated_and_charged_once_and_served_with_long_cache(http):
    english_deepgram()
    c, u = client_for("clip@x.in")
    body = {"text": "A table has rows and columns.", "lang": "en", "voice_role": "narrator"}
    first = c.post("/api/voice/clip/", body, format="json")
    assert first.status_code == 200 and first.data["cached"] is False
    assert first.data["url"].startswith("/api/media/speech/") and first.data["url"].endswith(".mp3")
    second = c.post("/api/voice/clip/", body, format="json")
    assert second.data == {**first.data, "cached": True}
    assert len(http.calls) == 1  # one provider call
    assert tts_chars(u) == len(body["text"])  # one charge

    other, other_user = client_for("clip2@x.in")  # every learner shares the clip
    assert other.post("/api/voice/clip/", body, format="json").data["url"] == first.data["url"]
    assert len(http.calls) == 1 and tts_chars(other_user) == 0

    audio = APIClient().get(first.data["url"])  # public by content hash, so <audio> can load it
    assert audio.status_code == 200 and audio["Content-Type"] == "audio/mpeg"
    assert audio["Cache-Control"] == "public, max-age=31536000, immutable"
    assert b"".join(audio.streaming_content) == MP3
    assert APIClient().get("/api/media/speech/../../etc.mp3").status_code == 404


def test_a_cleared_audio_file_is_made_again(http):
    from django.core.files.storage import default_storage

    english_deepgram()
    c, _ = client_for("gone@x.in")
    url = c.post("/api/voice/clip/", {"text": "Hello."}, format="json").data["url"]
    default_storage.delete(SpeechClip.objects.get().file)
    again = c.post("/api/voice/clip/", {"text": "Hello."}, format="json").data
    assert again["url"] == url and again["cached"] is False and len(http.calls) == 2
    assert APIClient().get(url).status_code == 200


def test_clip_limits_auth_and_browser_fallback(http):
    assert APIClient().post("/api/voice/clip/", {"text": "Hi"}, format="json").status_code == 401
    c, u = client_for("lim@x.in")
    assert c.post("/api/voice/clip/", {"text": "Hi"}, format="json").data["code"] == "use_browser_engine"
    english_deepgram()
    assert c.post("/api/voice/clip/", {"text": "x" * 601}, format="json").data["code"] in (
        "too_long",
        "bad_input",
    )
    assert c.post("/api/voice/clip/", {"text": "Hi", "voice_role": "dj"}, format="json").status_code == 400
    ProviderConfig.objects.filter(capability="tts").update(limits={"tts_chars_per_day": 10})
    over = c.post("/api/voice/clip/", {"text": "This line is too long for the budget."}, format="json")
    assert over.status_code == 429 and over.data["code"] == "voice_budget_exceeded"
    assert http.calls == [] and tts_chars(u) == 0


def test_failed_generation_is_refunded_and_not_cached(http, monkeypatch):
    english_deepgram()
    monkeypatch.setattr(
        adapters.httpx,
        "post",
        lambda url, **kw: httpx.Response(500, text="boom", request=httpx.Request("POST", url)),
    )
    c, u = client_for("fail@x.in")
    res = c.post("/api/voice/clip/", {"text": "Hello there."}, format="json")
    assert res.status_code == 502 and tts_chars(u) == 0 and not SpeechClip.objects.exists()


def test_rest_of_the_episode_is_prewarmed_in_the_background(http, django_capture_on_commit_callbacks):
    english_deepgram()
    c, u = client_for("warm@x.in")
    rest = [
        {"text": "Second line.", "lang": "en", "voice_role": "host_b"},
        {"text": "Third line.", "lang": "en", "voice_role": "host_a"},
    ]
    with django_capture_on_commit_callbacks(execute=True):
        res = c.post(
            "/api/voice/clip/", {"text": "First line.", "voice_role": "host_a", "warm": rest}, format="json"
        )
    assert res.status_code == 200 and SpeechClip.objects.count() == 3 and len(http.calls) == 3
    # The player's later requests for those lines are instant cache hits.
    for item in rest:
        assert c.post("/api/voice/clip/", item, format="json").data["cached"] is True
    assert len(http.calls) == 3


# ── language routing ─────────────────────────────────────────────────


def test_tamil_lines_use_tts_ta_when_set_else_tts(http):
    english_deepgram()
    c, _ = client_for("ta@x.in")
    # No Tamil voice yet: Tamil goes to "Speaking" (Deepgram, English only), which says so → the browser reads it.
    res = c.post("/api/voice/clip/", {"text": "வணக்கம் Kavya!", "lang": "en"}, format="json")
    assert res.status_code == 422 and res.data["code"] == "unsupported_language" and http.calls == []
    assert clips.route("ta")[0] == "tts"

    tamil_sarvam()
    assert clips.route("ta")[0] == "tts_ta" and clips.route("en")[0] == "tts"
    ta = c.post("/api/voice/clip/", {"text": "வணக்கம் Kavya!", "lang": "en"}, format="json")
    assert ta.status_code == 200 and ta.data["url"].endswith(".wav")
    url, kw = http.calls[-1]
    assert url == "https://api.sarvam.ai/text-to-speech" and kw["headers"]["api-subscription-key"] == SV
    assert kw["json"]["target_language_code"] == "ta-IN" and kw["json"]["speaker"] == "vijay_ta_narration"
    en = c.post("/api/voice/clip/", {"text": "Hello Kavya!", "lang": "en"}, format="json")
    assert en.status_code == 200 and http.calls[-1][0] == "https://api.deepgram.com/v1/speak"
    assert SpeechClip.objects.get(lang="ta").provider == "sarvam"
    assert SpeechClip.objects.get(lang="en").provider == "deepgram"
    assert c.get("/api/voice/config/").data["tts_ta"] == {"engine": "server", "provider": "sarvam"}


def test_tamil_without_its_own_key_falls_back_to_tts(http, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY")
    tamil_sarvam()
    ProviderConfig.objects.create(capability="tts", provider="google", model="standard")
    monkeypatch.setenv("GOOGLE_CLOUD_API_KEY", "g-key")
    assert clips.route("ta")[0] == "tts"


# ── two podcast hosts, two voices ────────────────────────────────────


def test_podcast_hosts_get_different_voices(http):
    english_deepgram()
    tamil_sarvam()
    tts, tts_ta = resolve("tts"), resolve("tts_ta")
    assert clips.voice_for(tts, "tts", "en", "host_a") == "aura-2-thalia-en"
    assert clips.voice_for(tts, "tts", "en", "host_b") == "aura-2-apollo-en"
    a, b = (
        clips.voice_for(tts_ta, "tts_ta", "ta", "host_a"),
        clips.voice_for(tts_ta, "tts_ta", "ta", "host_b"),
    )
    assert a != b and {a, b} <= {"gokul_ta_narration", "vijay_ta_narration"}

    c, _ = client_for("hosts@x.in")
    line = {"text": "So what is a table?", "lang": "en"}
    ua = c.post("/api/voice/clip/", {**line, "voice_role": "host_a"}, format="json").data["url"]
    ub = c.post("/api/voice/clip/", {**line, "voice_role": "host_b"}, format="json").data["url"]
    assert ua != ub
    models = [kw["params"]["model"] for _, kw in http.calls]
    assert models == ["aura-2-thalia-en", "aura-2-apollo-en"]


def test_admin_host_choices_are_used_and_never_collide(http):
    english_deepgram(en_host_a="aura-2-luna-en", en_host_b="aura-2-luna-en")
    tts = resolve("tts")
    assert clips.voice_for(tts, "tts", "en", "host_a") == "aura-2-luna-en"
    assert clips.voice_for(tts, "tts", "en", "host_b") not in ("aura-2-luna-en", "")
    ProviderConfig.objects.filter(capability="tts").update(voices={"en_host_b": "aura-2-orion-en"})
    assert clips.voice_for(resolve("tts"), "tts", "en", "host_b") == "aura-2-orion-en"


# ── migrations ───────────────────────────────────────────────────────


def test_migrations_are_present_for_the_new_models():
    out = StringIO()
    call_command("makemigrations", "providers", "--check", "--dry-run", stdout=out)
    assert "No changes detected" in out.getvalue()
