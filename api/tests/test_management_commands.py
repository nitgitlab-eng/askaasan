"""Management commands (R73): each runs through call_command, offline, with dummy users."""

import os
import time
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.models import User


def run(*args, **opts) -> str:
    out = StringIO()
    call_command(*args, stdout=out, stderr=StringIO(), **opts)
    return out.getvalue()


# ── make_admin / make_creator ──


@pytest.mark.django_db
@pytest.mark.parametrize(("command", "field"), [("make_admin", "is_staff"), ("make_creator", "is_creator")])
def test_grant_and_revoke_role(command, field):
    user = User.objects.create_user("Ravi.Role@example.com")
    assert "granted" in run(command, "RAVI.ROLE@example.com")  # matched case-insensitively
    user.refresh_from_db()
    assert getattr(user, field) is True
    assert "revoked" in run(command, "ravi.role@example.com", "--revoke")
    user.refresh_from_db()
    assert getattr(user, field) is False


@pytest.mark.django_db
@pytest.mark.parametrize("command", ["make_admin", "make_creator"])
def test_role_commands_reject_unknown_email(command):
    with pytest.raises(CommandError, match="No user"):
        run(command, "nobody@example.com")


# ── setup_env ──


EXAMPLE = "# comment\nDJANGO_SECRET_KEY=\nAASAN_SECRETS_KEY=\nDJANGO_DEBUG=true\n# OPTIONAL_THING=x\nNEW_KEY=placeholder\n"


@pytest.fixture
def env_dir(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    (tmp_path / ".env.example").write_text(EXAMPLE)
    return tmp_path


def test_setup_env_creates_env_with_generated_secrets(env_dir):
    out = run("setup_env")
    env = (env_dir / ".env").read_text()
    values = dict(line.split("=", 1) for line in env.splitlines() if line and not line.startswith("#"))
    assert len(values["DJANGO_SECRET_KEY"]) >= 50 and len(values["AASAN_SECRETS_KEY"]) >= 50
    assert values["DJANGO_SECRET_KEY"] != values["AASAN_SECRETS_KEY"]
    assert values["DJANGO_DEBUG"] == "true" and values["NEW_KEY"] == "placeholder"
    assert "OPTIONAL_THING" not in values  # commented-out examples stay out
    assert values["DJANGO_SECRET_KEY"] not in out and values["AASAN_SECRETS_KEY"] not in out  # never printed
    assert oct((env_dir / ".env").stat().st_mode & 0o777) == "0o600"


def test_setup_env_keeps_existing_values(env_dir):
    (env_dir / ".env").write_text("DJANGO_SECRET_KEY=keep-me\nDJANGO_DEBUG=false")
    out = run("setup_env")
    env = (env_dir / ".env").read_text()
    assert env.startswith("DJANGO_SECRET_KEY=keep-me\nDJANGO_DEBUG=false\n")
    assert env.count("DJANGO_SECRET_KEY=") == 1 and env.count("DJANGO_DEBUG=") == 1
    assert "AASAN_SECRETS_KEY=" in env and "NEW_KEY=placeholder" in env
    assert "keep-me" not in out
    assert "Added 0 placeholder(s)" in run("setup_env")  # idempotent


# ── seed_demo ──


@pytest.mark.django_db
def test_seed_demo_refuses_when_debug_is_off(settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="local development only"):
        run("seed_demo")
    assert not User.objects.filter(email__endswith="@aasan.test").exists()


@pytest.mark.django_db
def test_seed_demo_creates_the_demo_account(settings):
    from apps.accounts.management.commands.seed_demo import DEMO_EMAIL, DEMO_PASSWORD

    settings.DEBUG = True
    out = run("seed_demo")
    assert DEMO_EMAIL in out and DEMO_PASSWORD not in out
    user = User.objects.get(email=DEMO_EMAIL)
    assert user.check_password(DEMO_PASSWORD) and user.is_staff and user.email_verified
    run("seed_demo")  # re-running resets instead of failing
    assert User.objects.filter(email=DEMO_EMAIL).count() == 1


@pytest.mark.django_db
def test_seed_demo_full_builds_school_and_course(settings):
    from apps.orgs.models import Assignment, Organization

    settings.DEBUG = True
    out = run("seed_demo", "--full")
    assert "Demo ready" in out
    org = Organization.objects.get(slug="aasan-demo-school")
    assert Assignment.objects.filter(org=org).count() == 1
    run("seed_demo", "--full")  # idempotent: still one assignment
    assert Assignment.objects.filter(org=org).count() == 1


# ── scheduled jobs ──


@pytest.mark.django_db
def test_send_plan_reminders_runs():
    assert "soon" in run("send_plan_reminders")


@pytest.mark.django_db
def test_send_study_reminders_runs():
    assert run("send_study_reminders").startswith("sent ")


@pytest.mark.django_db
def test_clean_media_dry_run_keeps_files(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "aasan").mkdir()
    stale = tmp_path / "aasan" / ("a" * 32 + ".webp")
    stale.write_bytes(b"x")
    old = time.time() - 3 * 24 * 3600
    os.utime(stale, (old, old))
    run("clean_media", "--dry-run")
    assert stale.exists()
    run("clean_media")
    assert not stale.exists()  # unreferenced, ownerless and past the grace period


# ── check_llm / translate_ui (no network) ──


@pytest.mark.django_db
def test_check_llm_no_call_reports_missing_keys_without_network(monkeypatch):
    from apps.accounts.management.commands import check_llm
    from apps.providers.catalog import ENV_KEYS

    for name in ENV_KEYS.values():
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        check_llm, "complete_once", lambda *a, **k: pytest.fail("--no-call must not call a provider")
    )
    out = run("check_llm", "--no-call")
    assert "LLM_FORCE_PROVIDER=fake" in out
    assert "missing key" in out and "Some capabilities need attention" in out


def test_translate_ui_dry_run_writes_nothing(monkeypatch):
    from apps.accounts.management.commands import translate_ui

    before = {p.name: p.stat().st_mtime for p in translate_ui.LOCALES.glob("*.json")}
    out = run("translate_ui", "--langs", "hi", "--dry-run")
    assert out.startswith("hi: ")
    assert {p.name: p.stat().st_mtime for p in translate_ui.LOCALES.glob("*.json")} == before


def test_translate_ui_rejects_unknown_language():
    with pytest.raises(CommandError, match="unknown language"):
        run("translate_ui", "--langs", "xx", "--dry-run")
