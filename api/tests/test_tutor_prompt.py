from types import SimpleNamespace

from apps.accounts.preferences import default_preferences
from llm.prompts.tutor import build_tutor_system

PROFILE = SimpleNamespace(level="beginner", domain="ai", goals=["placement"], language="en")


def test_auto_mode_mirrors_language():
    text = build_tutor_system(PROFILE, default_preferences(), "Kili")
    assert "Mirror the learner's language" in text
    assert "across India" in text


def test_prompt_is_byte_stable_for_caching():
    prefs = default_preferences()
    assert build_tutor_system(PROFILE, prefs, "Kili") == build_tutor_system(PROFILE, prefs, "Kili")


def test_fixed_tamil_mode():
    prefs = default_preferences()
    prefs["mentor"]["reply_language"] = "ta"
    assert "Always reply in simple modern Tamil" in build_tutor_system(PROFILE, prefs, "Kili")
