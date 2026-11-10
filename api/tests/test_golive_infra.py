"""Go-live infra (contract section A): DB pool, readiness, request ids and logs, Celery reliability, fake-AI latency,
gunicorn sizing, and the compose / nginx stack. Static checks, no Docker needed."""

import asyncio
import json
import logging
import os
import runpy
import time
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from django.db import OperationalError
from django.utils import timezone

from config import health
from config.logs import JsonFormatter, RequestIdFilter
from config.settings import database_config
from llm.base import ChatMessage, LLMRequest
from llm.providers.fake_provider import FakeProvider

from .test_fix_infra import settings_in_subprocess

API = Path(__file__).resolve().parents[1]
REPO = API.parent
COMPOSE = yaml.safe_load((REPO / "infra" / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]
NGINX_MAIN = (REPO / "infra" / "nginx" / "nginx.conf").read_text()
NGINX_SITE = (REPO / "infra" / "nginx" / "default.conf").read_text()
PG = "postgres://aasan:pw@db:5432/aasan"


def _req(text="hello world"):
    return LLMRequest(model="fake", system="", messages=[ChatMessage("user", text)])


# ── database ──


def test_sqlite_stays_unpooled_with_persistent_connections(monkeypatch):
    monkeypatch.setenv("DB_POOL_MAX", "50")
    db = database_config("sqlite:////tmp/x.sqlite3")
    assert db["ENGINE"] == "django.db.backends.sqlite3"
    assert "pool" not in db.get("OPTIONS", {}) and db["CONN_MAX_AGE"] == 60


def test_postgres_uses_the_psycopg_pool_sized_from_env(monkeypatch):
    monkeypatch.delenv(
        "PYTEST_VERSION", raising=False
    )  # the pool is off under pytest; this checks prod config
    monkeypatch.setenv("DB_POOL_MIN", "3")
    monkeypatch.setenv("DB_POOL_MAX", "12")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "7")
    monkeypatch.delenv("DB_STATEMENT_TIMEOUT_MS", raising=False)
    db = database_config(PG)
    assert db["ENGINE"] == "django.db.backends.postgresql"
    assert db["CONN_MAX_AGE"] == 0  # Django refuses a pool with persistent connections
    assert db["OPTIONS"]["pool"] == {"min_size": 3, "max_size": 12, "timeout": 7.0}
    assert db["OPTIONS"]["options"] == "-c statement_timeout=30000"  # default cap
    assert db["OPTIONS"]["connect_timeout"] == 5
    import psycopg_pool  # noqa: F401 - the pool needs it installed

    monkeypatch.setenv("DB_STATEMENT_TIMEOUT_MS", "0")  # the migrate job
    assert "options" not in database_config(PG)["OPTIONS"]


def test_django_accepts_the_pool_config(monkeypatch):
    """Django builds the psycopg pool from it (unopened, so no server is needed) with the sizes and health checks."""
    from django.db.backends.postgresql.base import DatabaseWrapper
    from django.db.utils import ConnectionHandler

    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.setenv("DB_POOL_MIN", "1")
    monkeypatch.setenv("DB_POOL_MAX", "4")
    # A private handler and alias: on a Postgres test run "default" already owns a live pool with other sizes.
    wrapper = ConnectionHandler(
        {
            "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"},
            "poolcheck": database_config(PG),
        }
    )["poolcheck"]
    try:
        pool = wrapper.pool
        assert pool.min_size == 1 and pool.max_size == 4 and pool._check is not None
        assert "statement_timeout=30000" in pool.kwargs["options"]
    finally:
        DatabaseWrapper._connection_pools.pop("poolcheck", None)


def test_postgres_pool_defaults_in_a_fresh_process():
    r = settings_in_subprocess(
        "(s.DATABASES['default']['OPTIONS']['pool'], s.DATABASES['default']['CONN_MAX_AGE'])",
        DATABASE_URL=PG,
        DB_POOL_MIN="",
        DB_POOL_MAX="",
        PYTEST_VERSION="",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "({'min_size': 2, 'max_size': 10, 'timeout': 10.0}, 0)"


def test_no_pool_under_pytest():
    """channels' test communicator makes every socket pin a pooled connection, so tests run without the pool."""
    assert os.environ.get("PYTEST_VERSION")
    assert "pool" not in database_config(PG)["OPTIONS"]
    assert database_config(PG)["CONN_MAX_AGE"] == 0


# ── health ──


@pytest.mark.django_db
def test_liveness_and_readiness_ok(client):
    assert client.get("/api/health/").json() == {"ok": True}
    res = client.get("/api/health/ready/")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "checks": {"db": "ok", "cache": "ok", "channels": "ok"}}


@pytest.mark.django_db
def test_probes_answer_whatever_the_host_header(client):
    # Container probes use 127.0.0.1; production ALLOWED_HOSTS may only list the public domain.
    assert client.get("/api/health/ready/", HTTP_HOST="internal.invalid").status_code == 200
    assert client.get("/api/health/", HTTP_HOST="internal.invalid").status_code == 200


@pytest.mark.django_db
def test_readiness_503_when_the_database_fails(client, monkeypatch, caplog):
    from django.db import connection

    def broken(*a, **kw):
        raise OperationalError("could not connect to server: secret-host-name")

    monkeypatch.setattr(connection, "cursor", broken)
    with caplog.at_level(logging.ERROR, logger="aasan.health"):
        res = client.get("/api/health/ready/")
    assert res.status_code == 503
    body = res.json()
    assert body["ok"] is False and body["checks"]["db"] == "fail" and body["checks"]["cache"] == "ok"
    assert "secret-host-name" not in res.content.decode()  # reasons go to the log only
    assert any("db" in r.getMessage() for r in caplog.records)


@pytest.mark.django_db
def test_readiness_503_when_the_cache_fails(client, monkeypatch):
    from django.core.cache import cache

    def broken(*a, **kw):
        raise ConnectionError("redis down")

    monkeypatch.setattr(cache, "set", broken)
    res = client.get("/api/health/ready/")
    assert res.status_code == 503 and res.json()["checks"] == {"db": "ok", "cache": "fail", "channels": "ok"}


@pytest.mark.django_db
def test_readiness_503_when_the_channel_layer_fails(client, monkeypatch):
    def broken():
        raise TimeoutError

    monkeypatch.setitem(health.CHECKS, "channels", broken)
    res = client.get("/api/health/ready/")
    assert res.status_code == 503 and res.json()["checks"]["channels"] == "fail"


# ── request id and logs ──


@pytest.mark.django_db
def test_request_id_generated_and_echoed(client):
    rid = client.get("/api/legal/site/")["X-Request-ID"]
    assert len(rid) == 32 and int(rid, 16) >= 0
    assert client.get("/api/legal/site/", HTTP_X_REQUEST_ID="lb-abc.123")["X-Request-ID"] == "lb-abc.123"
    bad = client.get("/api/legal/site/", HTTP_X_REQUEST_ID="x" * 65 + "\n<script>")["X-Request-ID"]
    assert len(bad) == 32 and "<" not in bad  # malformed ids are replaced, never reflected
    assert client.get("/api/health/")["X-Request-ID"]


@pytest.mark.django_db
def test_slow_requests_are_logged_with_their_request_id(client, settings, caplog):
    settings.SLOW_REQUEST_MS = -1  # every request counts as slow
    with caplog.at_level(logging.WARNING, logger="aasan.request"):
        client.get("/api/legal/site/", HTTP_X_REQUEST_ID="req-slow-1")
    rec = next(r for r in caplog.records if r.name == "aasan.request")
    assert "slow request GET /api/legal/site/" in rec.getMessage()
    assert RequestIdFilter().filter(rec) and rec.request_id == "req-slow-1"
    settings.SLOW_REQUEST_MS = 60_000
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="aasan.request"):
        client.get("/api/legal/site/")
    assert not [r for r in caplog.records if r.name == "aasan.request"]


def test_json_log_lines_are_single_line_json():
    rec = logging.LogRecord("aasan.x", logging.ERROR, __file__, 1, "boom %s", ("a\nb",), None)
    rec.request_id = "rid-1"
    rec.duration_ms = 12
    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        rec.exc_info = sys.exc_info()
    line = JsonFormatter().format(rec)
    assert "\n" not in line
    out = json.loads(line)
    assert out["msg"] == "boom a\nb" and out["level"] == "ERROR" and out["request_id"] == "rid-1"
    assert out["duration_ms"] == 12 and "ValueError" in out["exc"]


def test_log_format_and_level_from_env():
    r = settings_in_subprocess(
        "(s.LOGGING['root']['level'], s.LOGGING['handlers']['stdout']['formatter'])",
        LOG_LEVEL="warning",
        DJANGO_DEBUG="true",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "('WARNING', 'plain')"
    r = settings_in_subprocess("s.LOGGING['handlers']['stdout']['formatter']", DJANGO_DEBUG="false")
    assert r.stdout.strip() == "json"


# ── fake provider latency ──


async def test_fake_provider_is_fast_by_default(settings):
    settings.LLM_FAKE_DELAY_MS = 0
    settings.LLM_FAKE_TOKEN_MS = 0
    p = FakeProvider()
    started = time.monotonic()
    assert await p.complete(_req())
    assert time.monotonic() - started < 0.05
    assert p.first_token == 0 and p.delay == 0.02  # unchanged per-chunk pacing


async def test_fake_provider_simulates_first_token_and_per_chunk_latency(settings):
    settings.LLM_FAKE_DELAY_MS = 150
    settings.LLM_FAKE_TOKEN_MS = 5
    p = FakeProvider()
    assert p.first_token == 0.15 and p.delay == 0.005
    started = time.monotonic()
    events = p.stream(_req())
    first = await anext(events)
    assert first.delta and time.monotonic() - started >= 0.15
    rest = [e async for e in events]
    assert rest[-1].done
    chunks = 1 + len(rest) - 1
    assert time.monotonic() - started >= 0.15 + 0.005 * chunks * 0.9

    started = time.monotonic()
    text = await p.complete(_req())
    assert time.monotonic() - started >= 0.15 + 0.005 * len(text.split(" ")) * 0.9

    started = time.monotonic()
    assert p.complete_sync(_req()) == text  # sync path sleeps with time.sleep
    assert time.monotonic() - started >= 0.15


def test_fake_provider_sleeps_without_blocking_the_loop(settings):
    settings.LLM_FAKE_DELAY_MS = 200
    settings.LLM_FAKE_TOKEN_MS = 0

    async def two_at_once():
        p = FakeProvider()
        started = time.monotonic()
        await asyncio.gather(p.complete(_req()), p.complete(_req()))
        return time.monotonic() - started

    assert asyncio.run(two_at_once()) < 0.35  # concurrent, not 0.4 s back to back


# ── Celery ──


def test_celery_reliability_settings():
    from config.celery import app

    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.broker_connection_retry_on_startup is True
    assert 0 < app.conf.task_soft_time_limit < app.conf.task_time_limit
    assert app.conf.broker_transport_options["visibility_timeout"] > app.conf.task_time_limit
    assert app.conf.worker_hijack_root_logger is False


def test_celery_concurrency_and_limits_from_env():
    r = settings_in_subprocess(
        "(s.CELERY_WORKER_CONCURRENCY, s.CELERY_TASK_SOFT_TIME_LIMIT, s.CELERY_TASK_TIME_LIMIT)",
        CELERY_CONCURRENCY="6",
        CELERY_SOFT_TIME_LIMIT="100",
        CELERY_TIME_LIMIT="120",
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "(6, 100, 120)"
    r = settings_in_subprocess("s.CELERY_WORKER_CONCURRENCY", CELERY_CONCURRENCY="")
    assert r.stdout.strip() == "None"  # Celery's default: one child per CPU


def test_email_and_notification_tasks_retry_with_backoff():
    from apps.accounts import tasks as accounts
    from apps.billing import tasks as billing
    from apps.workshops import tasks as workshops

    for task in (
        accounts.study_reminders,
        accounts.guardian_digest,
        accounts.push_deliver,
        accounts.evening_checks,
        accounts.winback_daily,
        accounts.stepup_checks,
        accounts.reminder_nightly,
        billing.plan_reminders,
        workshops.announce_run,
        workshops.notify_enrolled,
        workshops.notify_org_run,
        workshops.send_reminders,
    ):
        assert OperationalError in task.autoretry_for, task.name
        assert ConnectionError in task.autoretry_for, task.name
        assert task.retry_backoff and task.retry_jitter and task.max_retries == 5, task.name


@pytest.mark.django_db
def test_retried_notify_skips_learners_already_told():
    from apps.accounts.models import User
    from apps.game.models import Notification
    from apps.workshops import tasks
    from apps.workshops.content import seed
    from apps.workshops.models import Workshop, WorkshopEnrollment, WorkshopRun

    seed()
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug="quick-check"),
        audience="public",
        starts_at=timezone.now() + timedelta(days=2),
        status="scheduled",
    )
    users = [User.objects.create_user(f"n{i}@example.com", "Work#2026passwd") for i in range(3)]
    for u in users:
        WorkshopEnrollment.objects.create(run=run, user=u)

    assert tasks.notify_enrolled.apply(args=(run.id, "moved")).get() == 3
    # A retry (after an outage mid-loop) must not tell the same learners twice.
    Notification.objects.filter(user=users[2]).delete()
    assert tasks.notify_enrolled.apply(args=(run.id, "moved"), retries=1).get() == 1
    assert Notification.objects.filter(kind="workshop").count() == 3
    # A first attempt always tells everyone (a second move is real news).
    assert tasks.notify_enrolled.apply(args=(run.id, "moved")).get() == 3


# ── gunicorn ──


def test_gunicorn_workers_default_and_env(monkeypatch):
    conf = API / "config" / "gunicorn_conf.py"
    monkeypatch.setenv("WEB_CONCURRENCY", "0")
    ns = runpy.run_path(str(conf))
    assert ns["default_workers"](2) == 5 and ns["default_workers"](8) == 9 and ns["default_workers"](64) == 9
    assert ns["workers"] == ns["default_workers"]()
    assert ns["worker_class"] == "config.gunicorn_worker.AasanUvicornWorker"
    # Recycling drops live WebSockets, so it's opt-in (load test: 1012 closes mid-session).
    assert ns["max_requests"] == 0 and ns["max_requests_jitter"] > 0 and ns["graceful_timeout"] > 0
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    assert runpy.run_path(str(conf))["workers"] == 3


def test_uvicorn_worker_pings_websockets():
    from config.gunicorn_worker import AasanUvicornWorker

    kw = AasanUvicornWorker.CONFIG_KWARGS
    assert kw["ws_ping_interval"] > 0 and kw["ws_ping_timeout"] > 0
    assert kw["lifespan"] == "off" and kw["proxy_headers"] is False


# ── compose and nginx ──


def test_compose_serving_and_healthchecks():
    assert (
        "gunicorn" in SERVICES["api"]["command"] and "config.asgi:application" in SERVICES["api"]["command"]
    )
    assert "/api/health/ready/" in str(SERVICES["api"]["healthcheck"]["test"])
    assert "/api/health/ready/" in str(SERVICES["web"]["healthcheck"]["test"])
    assert "inspect ping" in str(SERVICES["worker"]["healthcheck"]["test"])
    assert "celerybeat-schedule" in str(SERVICES["beat"]["healthcheck"]["test"])
    assert "celerybeat:/var/lib/celery" in SERVICES["beat"]["volumes"]
    assert "/var/lib/celery/celerybeat-schedule" in SERVICES["beat"]["command"]
    assert SERVICES["worker"]["environment"]["CELERY_CONCURRENCY"].startswith("${CELERY_CONCURRENCY")
    assert SERVICES["migrate"]["environment"]["DB_STATEMENT_TIMEOUT_MS"] == "0"


def test_compose_postgres_and_redis_sizing():
    pg = " ".join(SERVICES["db"]["command"])
    assert "max_connections=${PG_MAX_CONNECTIONS:-300}" in pg and "shared_buffers=" in pg
    broker = SERVICES["redis"]["command"][-1]
    assert "--maxmemory-policy noeviction" in broker and "--appendonly yes" in broker
    assert "--maxmemory-policy allkeys-lru" in SERVICES["redis-cache"]["command"][-1]
    env = SERVICES["api"]["environment"]
    dbs = {env[k].rsplit("/", 1)[1] for k in ("REDIS_URL", "CACHE_REDIS_URL", "CHANNELS_REDIS_URL")}
    assert dbs == {"0", "1", "2"}  # separate DBs for broker, cache and channels


def test_channel_layer_limits_from_env():
    r = settings_in_subprocess(
        "s.CHANNEL_LAYERS['default']['CONFIG']",
        REDIS_URL="redis://r:6379/0",
        CHANNELS_REDIS_URL="redis://r:6379/2",
        CHANNELS_CAPACITY="500",
    )
    assert r.returncode == 0, r.stderr
    assert "'address': 'redis://r:6379/2'" in r.stdout and "'capacity': 500" in r.stdout
    assert "'socket_timeout': 30" in r.stdout  # must outlast channels_redis's 5 s blocking receive
    assert "'expiry': 60" in r.stdout and "'group_expiry': 86400" in r.stdout


def test_compose_mail_goes_to_mailpit_on_localhost_only():
    ports = SERVICES["mailpit"]["ports"]
    assert ports and all(p.startswith("127.0.0.1:") for p in ports)
    for name in ("api", "worker", "beat"):
        env = SERVICES[name]["environment"]
        assert env["EMAIL_HOST"] == "${EMAIL_HOST:-mailpit}" and env["EMAIL_PORT"] == "${EMAIL_PORT:-1025}"
        assert "smtp.EmailBackend" in env["EMAIL_BACKEND"]


def test_smtp_settings_from_env():
    r = settings_in_subprocess(
        "(s.EMAIL_HOST, s.EMAIL_PORT, s.EMAIL_USE_TLS)", EMAIL_HOST="mailpit", EMAIL_PORT="1025"
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "('mailpit', 1025, False)"


def test_nginx_scale_settings():
    assert "worker_connections 4096;" in NGINX_MAIN
    assert "limit_req_zone $binary_remote_addr zone=auth" in NGINX_MAIN
    assert "keepalive 64;" in NGINX_SITE
    auth = NGINX_SITE[NGINX_SITE.index("location ~ ^/api/users/(login") :]
    auth = auth[: auth.index("}")]
    assert "limit_req zone=auth" in auth and "register" in auth and "password-reset" in auth
    assert "security-headers.conf" in auth
    assert "gzip_proxied any;" in NGINX_SITE
    assert 'Cache-Control "public, max-age=31536000, immutable"' in NGINX_SITE
    ws = NGINX_SITE[NGINX_SITE.index("location /ws/") :]
    assert "proxy_read_timeout 3600s;" in ws[: ws.index("}")]
    proxy = (REPO / "infra" / "nginx" / "proxy.conf").read_text()
    assert "proxy_buffers" in proxy and 'Connection ""' in proxy and "X-Request-ID" in proxy
    dockerfile = (REPO / "infra" / "web.Dockerfile").read_text()
    assert "nginx/nginx.conf /etc/nginx/nginx.conf" in dockerfile and "proxy.conf" in dockerfile


def test_loadtest_overlay_forces_the_fake_provider():
    overlay = yaml.safe_load((REPO / "infra" / "docker-compose.loadtest.yml").read_text())
    for name in ("api", "worker", "beat"):
        env = overlay["services"][name]["environment"]
        assert env["LLM_FORCE_PROVIDER"] == "fake" and "LLM_FAKE_DELAY_MS" in env


def test_nginx_re_resolves_the_api_after_it_is_recreated():
    """Seen after a restart: nginx kept the old api container IP and answered 502 until restarted."""
    conf = (REPO / "infra" / "nginx" / "default.conf").read_text()
    assert "resolver 127.0.0.11" in conf
    assert "server api:8000 resolve;" in conf and "zone api_upstream" in conf


def test_csp_allows_google_sign_in():
    """The Google button is a script + iframe from accounts.google.com; its callbacks also fetch from there."""
    csp = (REPO / "infra" / "nginx" / "security-headers.conf").read_text()
    policy = csp[csp.index('Content-Security-Policy "') :].split("\n", 1)[0]
    for directive in ("script-src", "frame-src", "connect-src"):
        block = policy[policy.index(directive) :].split(";", 1)[0]
        assert "https://accounts.google.com" in block, directive
