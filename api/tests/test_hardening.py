"""Production settings refuse to start when a public site is left with unsafe defaults (config/hardening.py)."""

import os
import subprocess
import sys
from pathlib import Path

from config.hardening import is_local_url, production_problems

GOOD = {
    "frontend_url": "https://aasan.example.com",
    "allowed_hosts": ["aasan.example.com"],
    "secret_key": "k" * 60,
    "secrets_key": "fernet-key",
    "livekit_url": "ws://livekit:7880",
    "livekit_public_url": "wss://aasan.example.com/livekit",
    "livekit_key": "aasan",
    "livekit_secret": "s" * 64,
    "sentry_dsn": "https://key@sentry.example.com/1",
    "env_file_mode": 0o100600,
}


def test_a_well_configured_public_site_passes():
    assert production_problems(**GOOD) == []


def test_local_urls():
    assert is_local_url("http://localhost:8080") and is_local_url("ws://127.0.0.1:7880/x")
    assert is_local_url("http://app.localhost") and not is_local_url("https://aasan.example.com")
    assert not is_local_url("ws://203.0.113.7/livekit")


def test_each_unsafe_setting_is_named():
    cases = {
        "LIVEKIT": {"livekit_key": "devkey", "livekit_secret": "secret"},
        "FRONTEND_URL": {"frontend_url": "http://aasan.example.com"},
        "DJANGO_ALLOWED_HOSTS": {"allowed_hosts": ["localhost", "127.0.0.1"]},
        "DJANGO_SECRET_KEY": {"secret_key": "short"},
        "AASAN_SECRETS_KEY": {"secrets_key": ""},
        "SENTRY_DSN": {"sentry_dsn": ""},
        "chmod 600": {"env_file_mode": 0o100644},
    }
    for name, change in cases.items():
        problems = production_problems(**{**GOOD, **change})
        assert len(problems) == 1 and name in problems[0], name


def test_dev_livekit_keys_are_refused_even_over_plain_ws_on_a_public_address():
    bad = {**GOOD, "livekit_public_url": "ws://203.0.113.7:8080/livekit", "livekit_key": "devkey"}
    assert any("LIVEKIT" in p for p in production_problems(**bad))


def test_the_local_docker_stack_keeps_its_defaults():
    local = {
        "frontend_url": "http://localhost:8080",
        "allowed_hosts": ["localhost", "127.0.0.1", "api", "web"],
        "secret_key": "k" * 60,
        "secrets_key": "",
        "livekit_url": "ws://livekit:7880",
        "livekit_public_url": "ws://localhost:8080/livekit",
        "livekit_key": "devkey",
        "livekit_secret": "secret",
    }
    assert production_problems(**local) == []


def test_settings_refuse_to_load_with_dev_livekit_keys_on_a_public_site():
    api = Path(__file__).resolve().parents[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("DJANGO_", "LIVEKIT_", "FRONTEND_URL", "AASAN_SECRETS_KEY", "SENTRY_"))
    }
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="k" * 60,
        DJANGO_ALLOWED_HOSTS="aasan.example.com",
        FRONTEND_URL="https://aasan.example.com",
        AASAN_SECRETS_KEY="x",
        LIVEKIT_URL="ws://livekit:7880",
        LIVEKIT_PUBLIC_URL="wss://aasan.example.com/livekit",
        SENTRY_OPTIONAL="1",
        LIVEKIT_API_KEY="devkey",  # explicit, so api/.env (loaded without override) can't change the outcome
        LIVEKIT_API_SECRET="secret",
    )
    code = "import django; django.setup()"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=api, env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode != 0 and "LIVEKIT_API_KEY" in out.stderr
    env.update(LIVEKIT_API_KEY="aasan", LIVEKIT_API_SECRET="s" * 64)
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=api, env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr


def test_askaasan_go_live_settings_start_cleanly():
    """The public-address values in docs/GO-LIVE-askaasan.md load, and passkeys, CSRF and CORS follow the domain."""
    api = Path(__file__).resolve().parents[1]
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(
            ("DJANGO_", "LIVEKIT_", "FRONTEND_URL", "WEBAUTHN_", "AASAN_SECRETS_KEY", "SENTRY_")
        )
    }
    env.update(
        DJANGO_SETTINGS_MODULE="config.settings",
        DJANGO_DEBUG="false",
        DJANGO_SECRET_KEY="k" * 60,
        AASAN_SECRETS_KEY="x",
        FRONTEND_URL="https://askaasan.com",
        WEBAUTHN_ORIGIN="https://askaasan.com",
        WEBAUTHN_RP_ID="askaasan.com",
        DJANGO_ALLOWED_HOSTS="askaasan.com,www.askaasan.com,localhost,127.0.0.1,api,web",
        DJANGO_SECURE_SSL_REDIRECT="true",
        DJANGO_NUM_PROXIES="1",
        LIVEKIT_URL="ws://livekit:7880",
        LIVEKIT_PUBLIC_URL="wss://askaasan.com/livekit",
        LIVEKIT_API_KEY="aasan",
        LIVEKIT_API_SECRET="s" * 64,
        SENTRY_OPTIONAL="1",
    )
    code = (
        "import django; django.setup(); from django.conf import settings as s; "
        "print(s.CSRF_TRUSTED_ORIGINS, s.CORS_ALLOWED_ORIGINS, s.WEBAUTHN_RP_ID, s.SECURE_SSL_REDIRECT)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=api, env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == [
        "['https://askaasan.com']",
        "['https://askaasan.com']",
        "askaasan.com",
        "True",
    ]


def test_unset_sentry_can_be_accepted_on_purpose():
    assert production_problems(**{**GOOD, "sentry_dsn": "", "sentry_optional": True}) == []


def test_secrets_can_come_from_files(tmp_path):
    """NAME_FILE (Docker secrets / a secret manager's mount) wins over api/.env for every setting."""
    api = Path(__file__).resolve().parents[1]
    (tmp_path / "k").write_text("from-a-file\n")
    env = {k: v for k, v in os.environ.items() if not k.startswith("AASAN_SECRETS_KEY")}
    env.update(DJANGO_SETTINGS_MODULE="config.settings", AASAN_SECRETS_KEY_FILE=str(tmp_path / "k"))
    code = "import django; django.setup(); from django.conf import settings as s; print(s.AASAN_SECRETS_KEY)"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=api, env=env, capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "from-a-file"
