"""Sarvam Bulbul: each model has its own speakers. Seen live: bulbul:v4-flash with no voice chosen sent the v2
default 'anushka' and Sarvam answered 400 'Speaker anushka is not compatible with model bulbul:v4-flash'."""

from types import SimpleNamespace

import httpx
import pytest

from apps.providers.catalog import CAPABILITIES, SARVAM_VOICES
from apps.providers.voice import adapters
from apps.providers.voice.adapters import sarvam_speaker


def cfg(model, voices=None):
    return SimpleNamespace(provider="sarvam", key="sk-test", model=model, voices=voices or {})


def ok():
    return httpx.Response(
        200, json={"audios": ["UklGRg=="]}, request=httpx.Request("POST", "https://api.sarvam.ai/")
    )


@pytest.mark.parametrize(
    ("model", "lang", "saved", "expected"),
    [
        ("bulbul:v4-flash", "en", "", "shubh_en_narration"),  # the screenshot case
        ("bulbul:v4-flash", "ta", "", "vijay_ta_narration"),
        ("bulbul:v4-flash", "en", "anushka", "shubh_en_narration"),  # a v2 name never reaches v4
        (
            "bulbul:v4-flash",
            "ta",
            "aravind_ta_suspense",
            "aravind_ta_suspense",
        ),  # any v4-style persona is kept
        ("bulbul:v3", "en", "", "shubh"),
        ("bulbul:v3", "ta", "anushka", "gokul"),
        ("bulbul:v3", "en", "kavya", "kavya"),
        ("bulbul:v2", "en", "", "anushka"),
        ("bulbul:v2", "ta", "shubh_en_narration", "anushka"),
        ("bulbul:v9", "en", "", ""),  # unknown model, no saved voice: let Sarvam pick its default
        ("bulbul:v9", "en", "someone", "someone"),
    ],
)
def test_speaker_always_fits_the_model(model, lang, saved, expected):
    assert sarvam_speaker(model, lang, saved) == expected


def test_v4_flash_request_sends_a_compatible_speaker(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters.httpx, "post", lambda url, **kw: calls.append(kw) or ok())
    adapters.synthesize(cfg("bulbul:v4-flash"), "Hello Priya", "en")
    assert calls[0]["json"] == {
        "text": "Hello Priya",
        "target_language_code": "en-IN",
        "model": "bulbul:v4-flash",
        "speaker": "shubh_en_narration",
    }


def test_unknown_model_without_voice_omits_speaker(monkeypatch):
    calls = []
    monkeypatch.setattr(adapters.httpx, "post", lambda url, **kw: calls.append(kw) or ok())
    adapters.synthesize(cfg("bulbul:v9"), "Hi", "en")
    assert "speaker" not in calls[0]["json"]


def test_catalog_lists_models_and_per_model_voices():
    sarvam = CAPABILITIES["tts"]["providers"]["sarvam"]
    assert sarvam["default_model"] == "bulbul:v4-flash"
    assert set(sarvam["models"]) == set(SARVAM_VOICES) == set(sarvam["voices_by_model"])
    for model, voices in SARVAM_VOICES.items():
        assert voices["en"] and voices["ta"], model
