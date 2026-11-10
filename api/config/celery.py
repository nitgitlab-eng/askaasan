import os

from celery import Celery
from celery.signals import beat_init, task_failure, worker_process_init

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("aasan")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@worker_process_init.connect
def fresh_db_pools(**_kwargs):
    """A forked Celery child must not reuse a Postgres pool opened in the parent: its connections and worker threads
    belong to the parent process. Forget it (without closing the parent's sockets); the child opens its own."""
    try:
        from django.db.backends.postgresql.base import DatabaseWrapper
    except ImportError:  # pragma: no cover - psycopg is a dependency
        return
    DatabaseWrapper._connection_pools.clear()


@task_failure.connect
def count_failure(sender=None, **_kwargs):
    from config.metrics import count

    count("celery_task_failures", task=getattr(sender, "name", "unknown"))


BEAT_LOCK = "aasan:beat-singleton"


@beat_init.connect
def one_beat_only(sender=None, **_kwargs):
    """Two beats (e.g. the same compose file on two VMs) would send every reminder and reconcile twice. The first beat
    holds a lock in the broker Redis and renews it; another one exits at start-up instead of double-firing."""
    import os
    import socket
    import threading

    from django.conf import settings

    if not settings.REDIS_URL:
        return
    import redis

    client = redis.Redis.from_url(settings.REDIS_URL)
    me = f"{socket.gethostname()}:{os.getpid()}"
    if not client.set(BEAT_LOCK, me, nx=True, ex=60) and client.get(BEAT_LOCK) != me.encode():
        raise SystemExit(
            f"Another Celery beat is running ({client.get(BEAT_LOCK)!r}); run beat on one node only."
        )

    def renew():
        while True:
            threading.Event().wait(20)
            if client.get(BEAT_LOCK) in (None, me.encode()):
                client.set(BEAT_LOCK, me, ex=60)

    threading.Thread(target=renew, daemon=True, name="beat-lock").start()
