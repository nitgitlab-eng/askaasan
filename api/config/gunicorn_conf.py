"""gunicorn settings for the API: multi-process ASGI (uvicorn workers; Channels WebSockets work under them).

Run: gunicorn -c config/gunicorn_conf.py config.asgi:application
Fallback server (single process): daphne -b 0.0.0.0 -p 8000 config.asgi:application"""

import multiprocessing
import os


def default_workers(cpus: int | None = None) -> int:
    """2 x CPU + 1, capped at 9 (each worker holds its own DB pool; see DB_POOL_MAX)."""
    return min(2 * (cpus or multiprocessing.cpu_count()) + 1, 9)


bind = os.environ.get("GUNICORN_BIND", "0.0.0.0:8000")
workers = int(os.environ.get("WEB_CONCURRENCY") or 0) or default_workers()  # unset, empty or 0 = default
worker_class = "config.gunicorn_worker.AasanUvicornWorker"
# Recycle each worker after this many requests (with jitter, so they never all restart at once). Open WebSockets on
# a recycled worker close after graceful_timeout and the app reconnects.
# Off by default: recycling a worker drops every live WebSocket on it (close 1012). The 500-user load test showed workers
# recycling every few minutes (a request counter, not a leak: memory stayed flat). Set it only if memory creeps up.
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "0"))
max_requests_jitter = int(os.environ.get("GUNICORN_MAX_REQUESTS_JITTER", "500"))
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "30"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))  # worker heartbeat; async requests may run longer
keepalive = 75
accesslog = None  # nginx keeps the access log; Django logs slow requests with their request id
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()
proxy_protocol = False
control_socket_disable = True  # no runtime control socket in the container (HOME is read-only)
