"""H5: ai_grades budget charges are weighted by each call's max_tokens (1 unit per 2000 tokens, at least 1)."""

import pytest
from django.utils import timezone

from apps.accounts.models import User
from apps.providers.models import UsageCounter


def _used(user):
    row = UsageCounter.objects.filter(user=user, day=timezone.localdate(), metric="ai_grades").first()
    return row.amount if row else 0


@pytest.mark.django_db
def test_large_calls_cost_more_units_small_calls_one():
    from apps.paths.api import _charge
    from apps.study.assist import _ai_charge as hint_charge
    from apps.study.progress import _ai_charge as insight_charge

    u = User.objects.create_user(email="h5@example.com", password="x-Strong-pass-123")
    assert _charge(u, max_tokens=5000) is None  # career assessment
    assert _used(u) == 3
    assert _charge(u, max_tokens=3000) is None  # placement test
    assert _used(u) == 5
    assert hint_charge(u, max_tokens=1200) is None
    assert insight_charge(u, max_tokens=600) is None
    assert _used(u) == 7
    assert _charge(u) is None  # unknown size still costs one unit
    assert _used(u) == 8


@pytest.mark.django_db
def test_tutor_prompt_bounds_learner_goals():
    from llm.prompts.tutor import build_tutor_system

    u = User.objects.create_user(email="h74@example.com", password="x-Strong-pass-123")
    profile = u.profile
    profile.goals = ["x" * 300] * 5  # a row saved before the 10 x 80-char goals limit existed
    text = build_tutor_system(profile, {}, "Kili")
    goals = text.split("goals=", 1)[1].rsplit(".", 1)[0].split(".\n", 1)[0]
    assert goals.startswith("x" * 300) and len(goals) <= 400
