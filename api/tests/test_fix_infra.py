"""Deployment config regressions (R61-R70, S24-S26) and the shared cache setting. Static checks, no Docker needed."""

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

API = Path(__file__).resolve().parents[1]
REPO = API.parent
COMPOSE = yaml.safe_load((REPO / "infra" / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]
APP_SERVICES = ("migrate", "api", "worker", "beat")


def settings_in_subprocess(expr: str, **env) -> subprocess.CompletedProcess:
    """Import config.settings in a fresh interpreter with the given env (empty string = unset; api/.env never wins)."""
    base = {
        k: v for k, v in os.environ.items() if not k.startswith(("DJANGO_", "REDIS_URL", "CACHE_REDIS_URL"))
    }
    base.update(
        {
            "DJANGO_SECRET_KEY": "test-only-0123456789abcdef-0123456789abcdef",
            "REDIS_URL": "",
            "CACHE_REDIS_URL": "",
        }
    )
    base.update(env)
    code = f"import config.settings as s; print({expr})"
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=API,
        env=base,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# ── settings ──


def test_cache_is_local_memory_without_redis():
    r = settings_in_subprocess("s.CACHES['default']['BACKEND']")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "django.core.cache.backends.locmem.LocMemCache"


def test_cache_is_shared_redis_when_configured():
    r = settings_in_subprocess(
        "s.CACHES['default']['BACKEND'], s.CACHES['default']['LOCATION']",
        REDIS_URL="redis://redis:6379/0",
        CACHE_REDIS_URL="redis://redis:6379/1",
    )
    assert r.returncode == 0, r.stderr
    assert "RedisCache" in r.stdout and "redis://redis:6379/1" in r.stdout
    r = settings_in_subprocess("s.CACHES['default']['LOCATION']", REDIS_URL="redis://redis:6379/0")
    assert r.stdout.strip() == "redis://redis:6379/0"  # falls back to REDIS_URL


def test_missing_secret_key_fails_with_setup_hint():
    r = settings_in_subprocess("1", DJANGO_SECRET_KEY="", DJANGO_DEBUG="false")
    assert r.returncode != 0
    assert "DJANGO_SECRET_KEY is empty" in r.stderr and "setup_env" in r.stderr


# ── docker-compose ──


def test_only_nginx_publishes_a_port():
    published = {name for name, svc in SERVICES.items() if svc.get("ports")}
    # db, redis and the API (X-Forwarded-For trust) stay internal. LiveKit publishes only its WebRTC media ports
    # (media can't go through nginx); its signalling port 7880 stays internal, behind nginx's /livekit/.
    assert published == {"web", "mailpit", "livekit"}
    media = SERVICES["livekit"]["ports"]
    assert len(media) == 2 and not any("7880" in p for p in media)
    assert any(p.endswith("/udp") for p in media)
    assert all(
        p.startswith("127.0.0.1:") for p in SERVICES["mailpit"]["ports"]
    )  # local inbox: this machine only
    assert "minio" not in SERVICES


def test_no_hard_coded_credentials():
    text = (REPO / "infra" / "docker-compose.yml").read_text()
    assert "aasan:aasan@" not in text and "aasan-dev-secret" not in text
    assert "${POSTGRES_PASSWORD:?" in text and "${REDIS_PASSWORD:?" in text
    assert "--requirepass" in str(SERVICES["redis"]["command"])
    for name in APP_SERVICES:
        env = SERVICES[name]["environment"]
        assert "${REDIS_PASSWORD" in env["REDIS_URL"] and "${POSTGRES_PASSWORD" in env["DATABASE_URL"]


def test_app_services_share_media_debug_off_and_frontend_origin():
    for name in APP_SERVICES:
        svc = SERVICES[name]
        assert "mediafiles:/app/media" in svc["volumes"], name  # the worker processes lecture uploads too
        assert svc["environment"]["DJANGO_DEBUG"] == "false", name
        assert (
            ":8080" in svc["environment"]["FRONTEND_URL"] and ":8080" in svc["environment"]["WEBAUTHN_ORIGIN"]
        )


def test_one_shot_migrate_and_health_ordering():
    assert "migrate" in str(SERVICES["migrate"]["command"])
    assert SERVICES["migrate"]["depends_on"]["db"]["condition"] == "service_healthy"
    for name in ("api", "worker", "beat"):
        assert "migrate" not in str(SERVICES[name]["command"])
        assert SERVICES[name]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    assert SERVICES["web"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert "healthcheck" in SERVICES["db"] and "healthcheck" in SERVICES["redis"]


# ── images ──


def test_api_build_context_ignores_secrets_and_local_data():
    assert SERVICES["api"]["build"]["context"] == "../api"
    ignored = (API / ".dockerignore").read_text().split()
    for entry in (".env", "db.sqlite3", "media/", ".venv/", "staticfiles/"):
        assert entry in ignored


def test_web_build_context_is_allow_listed():
    text = (REPO / "infra" / "web.Dockerfile.dockerignore").read_text()
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert lines[0] == "*" and "!web/" in lines and "web/node_modules/" in lines


def test_api_image_runs_unprivileged_with_healthcheck():
    dockerfile = (REPO / "infra" / "api.Dockerfile").read_text()
    assert re.search(r"^USER (?!root)\S+", dockerfile, re.MULTILINE)
    assert "HEALTHCHECK" in dockerfile


def test_nginx_websocket_forwards_client_ip():
    conf = (REPO / "infra" / "nginx" / "default.conf").read_text()
    ws = conf[conf.index("location /ws/") :]
    ws = ws[: ws.index("}")]
    assert "X-Forwarded-For $proxy_add_x_forwarded_for" in ws
