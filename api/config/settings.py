"""Aasan API settings. Env-driven; sane local defaults (SQLite + in-memory channels)."""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from dotenv import load_dotenv

from config.hardening import production_problems
from config.logs import build_logging

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(name: str, default: str = "") -> str:
    """Like os.getenv, but an empty placeholder (`KEY=`) counts as unset. `NAME_FILE=/run/secrets/x` reads the value
    from that file instead (Docker secrets, or a secret manager's mounted file), so keys need not sit in api/.env."""
    if path := os.getenv(f"{name}_FILE"):
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or default
    return os.getenv(name) or default


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me-0123456789abcdef0123456789")
DEBUG = env_bool("DJANGO_DEBUG", False)  # fail closed: local dev sets DJANGO_DEBUG=true in .env
ALLOWED_HOSTS = env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "corsheaders",
    "channels",
    "apps.accounts",
    "apps.mentor",
    "apps.providers",
    "apps.learning",
    "apps.review",
    "apps.game",
    "apps.docs",
    "apps.roleplay",
    "apps.orgs",
    "apps.billing",
    "apps.legal",
    "apps.live",
    "apps.media",
    "apps.paths",
    "apps.study",
    "apps.studio",
    "apps.support",
    "apps.extension",
    "apps.guests",
    "apps.credentials",
    "apps.connect",
    "apps.calsync",
    "apps.journeys",
    "apps.workshops",
    "apps.adaptive",
    "apps.integrations",
]

MIDDLEWARE = [
    "config.middleware.RequestId",  # first: every log line and response carries the id
    "config.middleware.HealthCheck",  # probes answer before host checks and the HTTPS redirect
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.ResetUsageUser",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.accounts.staff.AdminAudit",  # records every admin-console change (after DRF has authenticated the user)
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def database_config(url: str) -> dict:
    """SQLite (dev, tests): unchanged, persistent connections. Postgres: Django 5.2's psycopg connection pool, one pool
    per process (gunicorn worker, Celery child) sized by DB_POOL_MIN / DB_POOL_MAX, so the total stays under the
    server's max_connections: (WEB_CONCURRENCY x DB_POOL_MAX) + (CELERY_CONCURRENCY x worker DB_POOL_MAX) + beat.
    The pool needs CONN_MAX_AGE=0 (a closed connection goes back to the pool). Every statement is capped by
    DB_STATEMENT_TIMEOUT_MS (0 = no cap; the one-shot migrate job uses 0)."""
    db = dj_database_url.parse(url, conn_max_age=60)
    if db["ENGINE"] == "django.db.backends.sqlite3":
        # Dev only: take the write lock at BEGIN and wait for it, instead of random "database is locked" 500s when
        # two requests read-then-write at once (seen in the e2e suite).
        db.setdefault("OPTIONS", {}).update({"transaction_mode": "IMMEDIATE", "timeout": 20})
        return db
    if db["ENGINE"] != "django.db.backends.postgresql":
        return db
    db["CONN_MAX_AGE"] = 0
    # The pool checks a connection before handing it out, so a Postgres restart doesn't surface as errors.
    db["CONN_HEALTH_CHECKS"] = True
    opts = db.setdefault("OPTIONS", {})
    # No pool under pytest: channels' test communicator replaces close_old_connections with a no-op, so every
    # WebSocket a test opens would pin a pooled connection until the communicator disconnects, and the suite dries
    # the pool up after a dozen sockets. Plain connections (one per thread, closed at test end) behave like prod.
    if not os.environ.get("PYTEST_VERSION"):
        opts["pool"] = {
            "min_size": int(env("DB_POOL_MIN", "2")),
            "max_size": int(env("DB_POOL_MAX", "10")),
            "timeout": float(env("DB_POOL_TIMEOUT", "10")),  # seconds to wait for a free connection
        }
    opts.setdefault("connect_timeout", int(env("DB_CONNECT_TIMEOUT", "5")))
    statement_ms = int(env("DB_STATEMENT_TIMEOUT_MS", "30000"))
    if statement_ms > 0:
        opts["options"] = f"{opts.get('options', '')} -c statement_timeout={statement_ms}".strip()
    # Migrations set this (compose `migrate`): a migration waiting on a busy table's lock gives up instead of queueing
    # every request behind its ACCESS EXCLUSIVE lock. Re-run it at a quieter moment.
    lock_ms = int(env("DB_LOCK_TIMEOUT_MS", "0"))
    if lock_ms > 0:
        opts["options"] = f"{opts.get('options', '')} -c lock_timeout={lock_ms}".strip()
    return db


DATABASES = {"default": database_config(env("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}"))}

# Redis, three roles: REDIS_URL = Celery broker (DB 0; never evicted), CHANNELS_REDIS_URL = WebSocket channel layer
# (DB 2; default REDIS_URL), CACHE_REDIS_URL = throttles and lockouts (DB 1; default REDIS_URL). Without Redis (local
# dev, tests): in-memory channels, per-process cache, Celery tasks run inline.
REDIS_URL = env("REDIS_URL") or None
CHANNELS_REDIS_URL = env("CHANNELS_REDIS_URL") or REDIS_URL
CHANNEL_LAYERS = {
    "default": (
        {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                # redis-py 8 defaults socket_timeout to 5 s, the same as channels_redis's 5 s blocking BZPOPMIN, so
                # idle sockets died with "Timeout reading from redis" (seen live). Read timeout must exceed that wait.
                "hosts": [
                    {
                        "address": CHANNELS_REDIS_URL,
                        "socket_timeout": int(env("CHANNELS_SOCKET_TIMEOUT", "30")),
                        "socket_connect_timeout": 5,
                        "socket_keepalive": True,
                        "health_check_interval": 30,
                    }
                ],
                # Messages queued per channel before sends fail, seconds an undelivered message lives, and
                # seconds a socket's group membership lasts.
                "capacity": int(env("CHANNELS_CAPACITY", "1000")),
                "expiry": int(env("CHANNELS_EXPIRY", "60")),
                "group_expiry": int(env("CHANNELS_GROUP_EXPIRY", "86400")),
            },
        }
        if CHANNELS_REDIS_URL
        else {"BACKEND": "channels.layers.InMemoryChannelLayer"}
    )
}
# Shared cache: DRF throttles and the login lockout must count across every daphne/worker process, so use Redis when
# there is one (its own DB, CACHE_REDIS_URL, so cache.clear() can't flush the Celery queue). Local dev: per-process memory.
CACHE_REDIS_URL = env("CACHE_REDIS_URL") or REDIS_URL
CACHES = {
    "default": (
        {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": CACHE_REDIS_URL,
            "KEY_PREFIX": "aasan",
            # A stalled Redis must fail fast (throttles run on every request), not hang the worker.
            "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
        }
        if CACHE_REDIS_URL
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    ),
}


def _redis_db(url: str, db: int) -> str:
    """The same Redis server as `url`, database `db`."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db}"))


# Security counters (login lockouts, OTP tries, mail caps) must survive memory pressure and restarts, so they sit on
# the never-evicting, persisted broker Redis (DB 3), not the LRU cache above. See apps/accounts/counters.py.
SECURITY_REDIS_URL = env("SECURITY_REDIS_URL") or (_redis_db(REDIS_URL, 3) if REDIS_URL else None)
CACHES["security"] = (
    {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": SECURITY_REDIS_URL,
        "KEY_PREFIX": "aasan-sec",
        "OPTIONS": {"socket_connect_timeout": 2, "socket_timeout": 2},
    }
    if SECURITY_REDIS_URL
    else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "security"}
)
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_TASK_ALWAYS_EAGER = not REDIS_URL
CELERY_TIMEZONE = "Asia/Kolkata"
# Reliability: a task is acknowledged only after it finishes, so a worker that dies mid-task hands it back to the
# queue; each child takes one task at a time; runaway tasks are stopped. Tasks must therefore be idempotent.
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = int(env("CELERY_SOFT_TIME_LIMIT", "900"))  # course generation can take minutes
CELERY_TASK_TIME_LIMIT = int(env("CELERY_TIME_LIMIT", "960"))
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
# Redis redelivers an unacknowledged task after this many seconds; keep it above the hard time limit.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": max(3600, CELERY_TASK_TIME_LIMIT * 2)}
CELERY_WORKER_CONCURRENCY = int(env("CELERY_CONCURRENCY", "0")) or None  # None = one child per CPU
CELERY_WORKER_MAX_TASKS_PER_CHILD = int(env("CELERY_MAX_TASKS_PER_CHILD", "200"))  # recycles leaky children
CELERY_WORKER_HIJACK_ROOT_LOGGER = False  # keep the one-line LOGGING format below
CELERY_BEAT_SCHEDULE = {
    "plan-reminders": {
        "task": "apps.billing.tasks.plan_reminders",
        "schedule": 6 * 60 * 60,
    },  # idempotent; every 6 h
    "payment-reconcile": {
        "task": "apps.billing.tasks.reconcile_payments",
        "schedule": 10 * 60,
    },  # captured but never granted (webhooks can't reach local/dev hosts); idempotent
    "study-reminders": {
        "task": "apps.accounts.tasks.study_reminders",
        "schedule": 15 * 60,
    },  # one per learner per day
    "clean-media": {"task": "apps.media.tasks.clean_media", "schedule": 24 * 60 * 60},
    "guardian-digest": {
        "task": "apps.accounts.tasks.guardian_digest",
        "schedule": 6 * 60 * 60,
    },  # Sundays; once per 7 days
    "workshop-agent-secrets": {
        "task": "apps.workshops.tasks.clean_agent_secrets",
        "schedule": 24 * 60 * 60,
    },  # learner MCP tokens are wiped after 7 days
    "workshop-reminders": {
        "task": "apps.workshops.tasks.send_reminders",
        "schedule": 5 * 60,
    },  # 24 h and 15 min before a public run; each once per learner
    "workshop-run-status": {
        "task": "apps.workshops.tasks.sync_run_status",
        "schedule": 5 * 60,
    },  # scheduled → live → ended (also computed on read)
    "sso-domain-recheck": {
        "task": "apps.orgs.tasks.recheck_domains",
        "schedule": 24 * 60 * 60,
    },  # SSO domains whose DNS TXT record is gone for 7 days are un-verified
    "webhook-retries": {
        "task": "apps.integrations.tasks.retry_webhooks",
        "schedule": 5 * 60,
    },  # failed deliveries whose retry time passed (a lost Celery message never strands one)
    "webhook-cleanup": {
        "task": "apps.integrations.tasks.cleanup_webhooks",
        "schedule": 24 * 60 * 60,
    },  # delivery log kept WEBHOOK_RETENTION_DAYS
    "workshop-retention": {
        "task": "apps.workshops.tasks.clean_old_activity",
        "schedule": 24 * 60 * 60,
    },  # workshop transcripts and events kept 90 days
    "llm-spend": {
        "task": "apps.providers.tasks.spend_check",
        "schedule": 60 * 60,
    },  # alerts at 50/80/95% of budget
    "data-retention": {
        "task": "apps.legal.tasks.apply_retention",
        "schedule": 24 * 60 * 60,
    },  # mentor chats, role-play transcripts, AI usage rows and speech clips (windows below)
    "evening-checks": {
        "task": "apps.accounts.tasks.evening_checks",
        "schedule": 15 * 60,
    },  # from each learner's nudge time (learned study time - 30 min, 08:00-21:30): streak at risk / reviews due
    "stepup-checks": {
        "task": "apps.accounts.tasks.stepup_checks",
        "schedule": 15 * 60,
    },  # day 1 / day 2 after a missed day (streak repair offer), plus the one back-off notice, daytime only
    "reminder-nightly": {
        "task": "apps.accounts.tasks.reminder_nightly",
        "schedule": crontab(minute=15, hour=3),
    },  # learned study times, back-off evaluation, PushLog pruning (90 days)
    "winback-daily": {
        "task": "apps.accounts.tasks.winback_daily",
        "schedule": crontab(minute=30, hour=10),
    },  # lapsed learners (3/7/30 days) and lapsed paid plans; each mail once per episode
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "apps.accounts.validators.BreachedPasswordValidator"},
]
# Refuse passwords seen in public breaches (Have I Been Pwned, k-anonymity: only 5 hash characters leave the server).
PASSWORD_BREACH_CHECK = env_bool("PASSWORD_BREACH_CHECK", True)

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["config.auth.MeteredJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {
        "auth": "20/min",
        "join": "10/hour",
        "push": "30/hour",
        "push_open": "60/hour",
    },
    # How many reverse proxies sit in front of Django (nginx = 1; nginx behind a load balancer = 2). The client IP
    # used for rate limits is taken that many hops from the right of X-Forwarded-For, so it can't be spoofed.
    "NUM_PROXIES": int(env("DJANGO_NUM_PROXIES", "0")),
}
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
}

DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024

FRONTEND_URL = env("FRONTEND_URL", "http://localhost:5173")
# Staff alerts (e.g. a subscription charge with the wrong amount): DJANGO_ADMINS="ops@example.com,owner@example.com"
ADMINS = [("Aasan staff", a.strip()) for a in env("DJANGO_ADMINS", "").split(",") if a.strip()]
# Certificates: minimum lesson score (0..1) on every lesson before a course certificate is issued.
CERT_PASS_SCORE = float(env("CERT_PASS_SCORE", "0.6"))
# Role-play: AI replies per learner per day, and XP-earning role-plays per learner per day.
ROLEPLAY_AI_DAILY = int(env("ROLEPLAY_AI_DAILY", "150"))
ROLEPLAY_REWARDS_PER_DAY = int(env("ROLEPLAY_REWARDS_PER_DAY", "5"))
# Guest links: % of the platform's daily guest-AI pool that free owners' links, and unverified owners' links, may use.
GUEST_AI_FREE_SHARE = int(env("GUEST_AI_FREE_SHARE", "80"))
GUEST_AI_NEW_SHARE = int(env("GUEST_AI_NEW_SHARE", "20"))
# ...and the % of that pool one free owner's links may use between them (paid owners: GUEST_AI_PER_OWNER_DAY only).
GUEST_AI_FREE_OWNER_SHARE = int(env("GUEST_AI_FREE_OWNER_SHARE", "2"))
# AI workshops: AI budget units per learner session (providers.ai_units, weighted by max_tokens), Help requests per
# learner per hour, and the safety cap (× the planned duration per day) after which only AI turns pause.
WORKSHOP_SESSION_AI_UNITS = int(env("WORKSHOP_SESSION_AI_UNITS", "400"))
WORKSHOP_HELP_PER_HOUR = int(env("WORKSHOP_HELP_PER_HOUR", "20"))
WORKSHOP_CAP_MULTIPLIER = float(env("WORKSHOP_CAP_MULTIPLIER", "3"))
# Agent builder (M2): test messages per session, learner MCP servers (an org can also switch them off with its
# `external_mcp` feature), and external MCP requests per learner per minute.
WORKSHOP_AGENT_RUNS = int(env("WORKSHOP_AGENT_RUNS", "40"))
WORKSHOP_EXTERNAL_MCP = env_bool("WORKSHOP_EXTERNAL_MCP", True)
WORKSHOP_EXTERNAL_PER_MIN = int(env("WORKSHOP_EXTERNAL_PER_MIN", "30"))
# Organisation API (/api/v1/): requests per API key, and how long the webhook delivery log is kept.
API_KEY_RATE = env("API_KEY_RATE", "600/hour")
WEBHOOK_RETENTION_DAYS = int(env("WEBHOOK_RETENTION_DAYS", "30"))
CORS_ALLOWED_ORIGINS = [FRONTEND_URL]
CSRF_TRUSTED_ORIGINS = [FRONTEND_URL]

# Speech-to-text is charged by clip size at this many bytes per second (750 = 6 kbps, a conservative Opus floor).
STT_CHARGE_BYTES_PER_SEC = int(env("STT_CHARGE_BYTES_PER_SEC", "4000"))
# Live conversation (ws/voice-stream/, Deepgram streaming): one socket is closed after this many minutes.
VOICE_STREAM_MAX_MINUTES = float(env("VOICE_STREAM_MAX_MINUTES", "30"))

# Live web search in mentor chat, Ask Aasan voice, Lesson Ask and Live Class (the provider's own search tool).
MENTOR_WEB_SEARCH = env_bool("MENTOR_WEB_SEARCH", True)
MENTOR_WEB_SEARCH_PER_DAY = int(env("MENTOR_WEB_SEARCH_PER_DAY", "30"))
# Never shown to learners (adult, gambling/betting, piracy). Comma-separated; replaces the default list when set.
WEB_SEARCH_BLOCKED_DOMAINS = [
    d.strip()
    for d in env(
        "WEB_SEARCH_BLOCKED_DOMAINS",
        "pornhub.com,xvideos.com,xnxx.com,xhamster.com,onlyfans.com,stake.com,dream11.com,bet365.com,1xbet.com,"
        "parimatch.com,thepiratebay.org,1337x.to,tamilrockers.com,isaimini.com,tamilyogi.com",
    ).split(",")
    if d.strip()
]
# Live voice (LiveKit): a WebRTC room per conversation with Aasan's voice agent (manage.py run_voice_agent).
# LIVEKIT_URL is how the agent and the API reach the server; LIVEKIT_PUBLIC_URL is what the browser connects to.
LIVEKIT_URL = env("LIVEKIT_URL")
LIVEKIT_PUBLIC_URL = env("LIVEKIT_PUBLIC_URL") or LIVEKIT_URL
# A self-hosted LiveKit in dev mode (`livekit-server --dev`) uses its built-in pair devkey / secret, so nothing has to
# be set locally. A public site must set its own pair (and start the server with it), or it refuses to start.
LIVEKIT_API_KEY = env("LIVEKIT_API_KEY") or ("devkey" if LIVEKIT_URL else "")
LIVEKIT_API_SECRET = env("LIVEKIT_API_SECRET") or ("secret" if LIVEKIT_URL else "")
LIVEKIT_AGENT_NAME = env("LIVEKIT_AGENT_NAME", "aasan-voice")
# A live voice call (LiveKit) ends after this many minutes; the learner can start another.
VOICE_LIVE_MAX_MINUTES = float(env("VOICE_LIVE_MAX_MINUTES", "30"))
# Live voice calls one host takes at once (each holds 200–400 MB in the voice agent; size to VOICE_AGENT_MEMORY).
VOICE_LIVE_MAX_CALLS = int(env("VOICE_LIVE_MAX_CALLS", "12"))

# Data retention in days (apps/legal/tasks.py, nightly; shown on the privacy page). 0 keeps forever.
MENTOR_RETENTION_DAYS = int(env("MENTOR_RETENTION_DAYS", "365"))  # conversations untouched this long
ROLEPLAY_RETENTION_DAYS = int(env("ROLEPLAY_RETENTION_DAYS", "365"))  # role-play transcripts
LLM_USAGE_RETENTION_DAYS = int(
    env("LLM_USAGE_RETENTION_DAYS", "400")
)  # AI usage rows (token counts, no content)
SPEECH_CLIP_RETENTION_DAYS = int(env("SPEECH_CLIP_RETENTION_DAYS", "180"))  # generated speech audio

# Admin console changes need a sign-in (passkey or email code for staff, see below) within this many minutes; 0 = off.
ADMIN_REAUTH_MINUTES = int(env("ADMIN_REAUTH_MINUTES", "30"))
# Staff prove admin changes with a passkey or an emailed code, not a password alone (once email works).
STAFF_SECOND_FACTOR = env_bool("STAFF_SECOND_FACTOR", True)

# Encrypts provider API keys saved from the admin console.
AASAN_SECRETS_KEY = env("AASAN_SECRETS_KEY")
# Previous AASAN_SECRETS_KEY value(s), comma-separated, still accepted for decrypting while you rotate.
AASAN_SECRETS_KEY_OLD = env("AASAN_SECRETS_KEY_OLD")

GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", "")
# Web push (VAPID). `manage.py setup_env` generates a key pair; without both keys push is off and the app hides it.
WEBPUSH_VAPID_PUBLIC_KEY = env("WEBPUSH_VAPID_PUBLIC_KEY")
WEBPUSH_VAPID_PRIVATE_KEY = env("WEBPUSH_VAPID_PRIVATE_KEY")
WEBPUSH_VAPID_SUBJECT = env("WEBPUSH_VAPID_SUBJECT", "mailto:support@aasan.local")
WEBPUSH_ENABLED = env_bool("WEBPUSH_ENABLED", True)
# Browsers' push services. A subscription endpoint must be https on one of these (no SSRF through a crafted endpoint).
WEBPUSH_ENDPOINT_HOSTS = [
    h.strip().lower()
    for h in env(
        "WEBPUSH_ENDPOINT_HOSTS",
        "fcm.googleapis.com,updates.push.services.mozilla.com,*.notify.windows.com,web.push.apple.com,*.push.apple.com",
    ).split(",")
    if h.strip()
]
WEBAUTHN_RP_ID = env("WEBAUTHN_RP_ID", "localhost")
WEBAUTHN_RP_NAME = "Aasan"
WEBAUTHN_ORIGIN = env("WEBAUTHN_ORIGIN", FRONTEND_URL)

# Admin console → Email (SMTP) wins; until it's set, mail goes to EMAIL_BACKEND from .env (console in dev).
EMAIL_BACKEND = "apps.legal.mail.ConfigurableEmailBackend"
EMAIL_FALLBACK_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
# Used when EMAIL_BACKEND is the SMTP backend (docker compose: the local mailpit inbox unless infra/.env says otherwise).
EMAIL_HOST = env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "Aasan <no-reply@aasan.local>")

# LLM routing: task -> "provider:model". Override any task via env LLM_ROUTE_<TASK>.
LLM_ROUTES = {
    "tutor": "anthropic:claude-sonnet-5-5",
    "author": "anthropic:claude-sonnet-5-5",
    "grade": "anthropic:claude-haiku-5-5",
    "suggest": "anthropic:claude-haiku-5-5",
    "onboarding": "anthropic:claude-haiku-5-5",
    "org_ask": "anthropic:claude-haiku-5-5",
}
for _task in list(LLM_ROUTES):
    if env(f"LLM_ROUTE_{_task.upper()}"):
        LLM_ROUTES[_task] = env(f"LLM_ROUTE_{_task.upper()}")
# "fake" provider lets the app run offline and powers tests.
LLM_FORCE_PROVIDER = env("LLM_FORCE_PROVIDER", "")
# Providers to fall back to, in order, when the configured one is rate-limited or down (e.g. "gemini,openai"; needs
# their keys in the admin console or .env). Empty = no failover. A failing provider is skipped this many seconds.
LLM_FALLBACK = env("LLM_FALLBACK", "")
LLM_BREAKER_SECONDS = int(env("LLM_BREAKER_SECONDS", "60"))
# Monthly AI budget in rupees: staff get an email at 50%, 80% and 95% (apps/providers/tasks.py). 0 = no alerts.
LLM_MONTHLY_BUDGET = int(env("LLM_MONTHLY_BUDGET", "0"))
# Load tests: make the fake provider as slow as a real model (time to first token, then per streamed chunk). 0 = off.
LLM_FAKE_DELAY_MS = int(env("LLM_FAKE_DELAY_MS", "0"))
LLM_FAKE_TOKEN_MS = int(env("LLM_FAKE_TOKEN_MS", "0"))

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True
# Production hardening (behind a TLS-terminating proxy that sets X-Forwarded-Proto).
if not DEBUG:
    MIDDLEWARE.insert(
        MIDDLEWARE.index("django.middleware.security.SecurityMiddleware") + 1,
        "whitenoise.middleware.WhiteNoiseMiddleware",
    )
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(
        env("DJANGO_HSTS_SECONDS", "31536000")
    )  # a public site must be https (hardening.py)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_HSTS_SUBDOMAINS", False)
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"
    # HSTS preload is a one-way listing the owner must opt into deliberately; don't nag about it in `check --deploy`.
    SILENCED_SYSTEM_CHECKS = ["security.W021"]
    # The health check is plain HTTP from inside the container; never redirect it to HTTPS.
    SECURE_REDIRECT_EXEMPT = [r"^api/health/(ready/)?$"]
    if SECRET_KEY.startswith("dev-insecure"):
        raise RuntimeError(
            "DJANGO_SECRET_KEY is empty and DJANGO_DEBUG is off. Run `uv run python manage.py setup_env` in api/ "
            "(it generates DJANGO_SECRET_KEY and AASAN_SECRETS_KEY in api/.env), or set DJANGO_SECRET_KEY yourself."
        )
    _problems = production_problems(
        frontend_url=FRONTEND_URL,
        allowed_hosts=ALLOWED_HOSTS,
        secret_key=SECRET_KEY,
        secrets_key=AASAN_SECRETS_KEY,
        livekit_url=LIVEKIT_URL,
        livekit_public_url=LIVEKIT_PUBLIC_URL,
        livekit_key=LIVEKIT_API_KEY,
        livekit_secret=LIVEKIT_API_SECRET,
        sentry_dsn=env("SENTRY_DSN"),
        sentry_optional=env_bool("SENTRY_OPTIONAL"),
        env_file_mode=(BASE_DIR / ".env").stat().st_mode if (BASE_DIR / ".env").exists() else None,
    )
    if _problems:
        raise RuntimeError("Unsafe production settings:\n- " + "\n- ".join(_problems))

STATIC_URL = "api/static/"  # under /api so the web proxy forwards it
STATIC_ROOT = BASE_DIR / "staticfiles"
# Lesson images. Docker mounts a volume here; files are served by /api/media/<name>.
MEDIA_ROOT = env("MEDIA_ROOT", str(BASE_DIR / "media"))
MEDIA_URL = "api/media/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Logs: one line per record on stdout, tagged with the request id. LOG_FORMAT = json | plain.
LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = env("LOG_FORMAT", "plain" if DEBUG else "json")
LOGGING = build_logging(LOG_LEVEL, LOG_FORMAT if LOG_FORMAT in {"json", "plain"} else "json")
SLOW_REQUEST_MS = int(env("SLOW_REQUEST_MS", "1000"))
HEALTH_TIMEOUT = float(env("HEALTH_TIMEOUT", "2"))
METRICS_TOKEN = env("METRICS_TOKEN")  # /api/metrics/ (Prometheus) needs it as a Bearer token; empty = off
HEALTH_CACHE_SECONDS = float(env("HEALTH_CACHE_SECONDS", "5"))  # readiness answers reused this long

# Optional error monitoring: set SENTRY_DSN to turn it on. No personal data (emails, request bodies) is sent.
if env("SENTRY_DSN"):
    import sentry_sdk

    sentry_sdk.init(
        dsn=env("SENTRY_DSN"),
        send_default_pii=False,
        traces_sample_rate=float(env("SENTRY_TRACES", "0")),
        environment="production" if not DEBUG else "development",
    )
