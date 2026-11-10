"""The learner's own companion (Kili / Mayil / Yaanai or a custom name) speaks in companion prompts."""

import pytest

from apps.accounts.companion import as_companion, companion
from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def _user(email, **mascot):
    u = User.objects.create_user(email, "Comp#2026pass")
    data = u.preferences.data
    data["mascot"] = {**data.get("mascot", {}), **mascot}
    u.preferences.data = data
    u.preferences.save()
    return u


def test_default_and_custom_companions():
    assert companion(_user("a@x.in"))["name"] == "Kili"
    m = companion(_user("b@x.in", character="mayil", name="Mayil"))
    assert m["name"] == "Mayil" and "peacock" in m["persona"]
    assert (
        companion(_user("c@x.in", character="yaanai", name="Kili"))["name"] == "Yaanai"
    )  # default name follows the character
    assert companion(_user("d@x.in", character="yaanai", name="Appu"))["name"] == "Appu"


def test_prompt_speaks_as_the_learners_companion():
    from llm.prompts.study import HINT_SYSTEM

    u = _user("e@x.in", character="mayil", name="Mayil")
    s = as_companion(HINT_SYSTEM.format(level=1, words=40, lang_rule="Reply in English."), u)
    assert "You are Mayil, a graceful, colourful peacock" in s and "Kili" not in s
    assert s.startswith("[[TASK:activity_hint]]")  # task marker untouched


def test_hint_endpoint_uses_companion(monkeypatch):
    from tests.test_study import _lesson

    u = _user("f@x.in", character="yaanai", name="Yaanai")
    from rest_framework.test import APIClient

    c = APIClient()
    c.force_authenticate(u)
    _, _, (quiz, *_) = _lesson(u)
    seen = {}
    from llm import structured

    orig = structured.complete_json_sync

    def spy(task, system, *a, **k):
        seen["system"] = system
        return orig(task, system, *a, **k)

    monkeypatch.setattr(structured, "complete_json_sync", spy)
    c.post(f"/api/study/activities/{quiz.id}/hint/", {"level": 1}, format="json")
    assert "You are Yaanai, a wise, patient elephant" in seen.get("system", "")
