"""/api/metrics/: Prometheus text format for the monitoring overlay (infra/docker-compose.monitoring.yml).

Needs `Authorization: Bearer <METRICS_TOKEN>`; without METRICS_TOKEN the endpoint is off (404). Counters that happen
in many processes (task failures, LLM errors) are kept in the shared cache by `count()`."""

import hmac
import shutil
import time

from django.conf import settings
from django.http import HttpResponse

PREFIX = "metrics:"


def count(name: str, **labels) -> None:
    """Add one to a shared counter (never raises: metrics must not break the work they describe)."""
    from django.core.cache import cache

    key = PREFIX + name + "|" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    try:
        cache.add(PREFIX + "keys", set(), None)
        keys = cache.get(PREFIX + "keys") or set()
        if key not in keys:
            cache.set(PREFIX + "keys", keys | {key}, None)
        cache.add(key, 0, None)
        cache.incr(key)
    except Exception:  # noqa: BLE001, S110
        pass


def _redis_info(url: str) -> dict:
    import redis

    client = redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    try:
        return client.info("memory") | {"queue": client.llen("celery")}
    finally:
        client.close()


def _lines() -> list[str]:
    from django.core.cache import cache
    from django.db import connection
    from django.utils import timezone

    out = ["aasan_up 1", f"aasan_scrape_timestamp_seconds {int(time.time())}"]
    for role, url in (("broker", settings.REDIS_URL), ("cache", settings.CACHE_REDIS_URL)):
        if not url:
            continue
        try:
            info = _redis_info(url)
        except Exception:  # noqa: BLE001
            out.append(f'aasan_redis_up{{role="{role}"}} 0')
            continue
        out.append(f'aasan_redis_up{{role="{role}"}} 1')
        out.append(f'aasan_redis_used_memory_bytes{{role="{role}"}} {info.get("used_memory", 0)}')
        out.append(f'aasan_redis_maxmemory_bytes{{role="{role}"}} {info.get("maxmemory", 0)}')
        if role == "broker":
            out.append(f"aasan_celery_queue_length {info['queue']}")
    if connection.vendor == "postgresql":
        with connection.cursor() as cur:
            cur.execute("SELECT count(*), current_setting('max_connections')::int FROM pg_stat_activity")
            used, cap = cur.fetchone()
        out += [f"aasan_db_connections {used}", f"aasan_db_max_connections {cap}"]
    disk = shutil.disk_usage(settings.MEDIA_ROOT if settings.MEDIA_ROOT else ".")
    out += [
        f'aasan_disk_free_bytes{{path="media"}} {disk.free}',
        f'aasan_disk_total_bytes{{path="media"}} {disk.total}',
    ]
    from apps.integrations.models import WebhookDelivery

    hour = timezone.now() - timezone.timedelta(hours=1)
    failed = WebhookDelivery.objects.filter(created_at__gte=hour, status__in=("failed", "dead")).count()
    out.append(f"aasan_webhook_failures_last_hour {failed}")
    for key in sorted(cache.get(PREFIX + "keys") or ()):
        name, _, labels = key[len(PREFIX) :].partition("|")
        out.append(f"aasan_{name}_total{{{labels}}} {cache.get(key) or 0}")
    return out


def metrics(request):
    token = settings.METRICS_TOKEN
    if not token:
        return HttpResponse(status=404)
    given = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        return HttpResponse(status=401)
    return HttpResponse("\n".join(_lines()) + "\n", content_type="text/plain; version=0.0.4")
