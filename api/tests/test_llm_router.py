import pytest

from apps.providers.models import ProviderConfig
from llm.base import LLMError
from llm.router import resolve

pytestmark = pytest.mark.django_db


@pytest.fixture
def real(settings, monkeypatch):
    settings.LLM_FORCE_PROVIDER = ""
    settings.LLM_ROUTES = {"tutor": "anthropic:claude-sonnet-5-5", "grade": "anthropic:claude-haiku-5-5"}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_missing_key_raises_clear_error(real):
    with pytest.raises(LLMError) as exc:
        resolve("tutor")
    assert exc.value.code == "provider_not_configured"


def test_env_key_used_when_no_admin_config(real, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-not-real")
    provider, model = resolve("grade")
    assert provider.name == "anthropic" and model == "claude-haiku-5-5"


def test_admin_config_overrides_env(real, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-not-real")
    row = ProviderConfig(capability="tutor", provider="openai", model="gpt-5-mini")
    row.set_key("sk-admin-key-not-real")
    row.save()
    provider, model = resolve("tutor")
    assert provider.name == "openai" and model == "gpt-5-mini"


def test_disabled_capability(real, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-not-real")
    ProviderConfig.objects.create(
        capability="utility", provider="anthropic", model="claude-haiku-5-5", enabled=False
    )
    with pytest.raises(LLMError):
        resolve("grade")
