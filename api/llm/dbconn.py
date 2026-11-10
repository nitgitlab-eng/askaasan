"""Hand the database connection back before a slow AI call.

Sync code (views, Celery tasks, socket handlers via database_sync_to_async) keeps its Django connection checked out of the
psycopg pool until the work finishes, even while it waits seconds on a model. Under the 500-user load test every pooled
connection ended up idle behind AI calls and other requests failed with PoolTimeout. Outside a transaction it is safe to
close (return) it now: the next query takes a fresh one from the pool."""

from django.db import connections


def release_db() -> None:
    for conn in connections.all(initialized_only=True):
        if conn.connection is not None and not conn.in_atomic_block:
            conn.close()
