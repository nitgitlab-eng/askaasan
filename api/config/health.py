"""Liveness and readiness probes.

/api/health/        liveness: the process answers. No I/O, so it stays cheap under load.
/api/health/ready/  readiness: the database, the shared cache and the channel layer each answer within
                    HEALTH_TIMEOUT seconds (default 2). 200 when all pass, 503 otherwise. The body names each check
                    as "ok" or "fail" only; the reason goes to the log, never to the caller."""

import asyncio
import logging
import time
import uuid

from asgiref.sync import async_to_sync
from django.conf import settings
from django.http import JsonResponse

log = logging.getLogger("aasan.health")


def live(request):
    return JsonResponse({"ok": True})


def check_db() -> None:
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()


def check_cache() -> None:
    from django.core.cache import cache

    key = f"health:{uuid.uuid4().hex}"
    cache.set(key, "1", timeout=10)
    if cache.get(key) != "1":
        raise RuntimeError("cache read-back mismatch")
    cache.delete(key)


async def _channel_roundtrip() -> None:
    from channels.layers import get_channel_layer

    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError("no channel layer configured")
    hosts = getattr(layer, "hosts", None)
    if hosts:
        # Redis layer: ping each shard on a throwaway client. A send/receive round trip here would bind channels_redis's
        # receive machinery to this request's short-lived event loop (async_to_sync), and later checks then hang.
        import redis.asyncio as aioredis

        for host in hosts:
            client = aioredis.from_url(host["address"], socket_timeout=settings.HEALTH_TIMEOUT)
            try:
                await asyncio.wait_for(client.ping(), settings.HEALTH_TIMEOUT)
            finally:
                await client.aclose()
        return
    channel = await layer.new_channel("health.")
    await asyncio.wait_for(layer.send(channel, {"type": "health.ping"}), settings.HEALTH_TIMEOUT)
    msg = await asyncio.wait_for(layer.receive(channel), settings.HEALTH_TIMEOUT)
    if msg.get("type") != "health.ping":
        raise RuntimeError("channel layer read-back mismatch")


def check_channels() -> None:
    async_to_sync(_channel_roundtrip)()


CHECKS = {"db": check_db, "cache": check_cache, "channels": check_channels}
_last: tuple[float, dict, bool] | None = None  # (when, results, ok): this process's latest answer


def ready(request):
    """Answers anonymous callers on any host, so a burst of probes reuses one answer for HEALTH_CACHE_SECONDS instead
    of hitting the database and both Redis servers per request (nginx also rate-limits /api/health/)."""
    global _last
    ttl = settings.HEALTH_CACHE_SECONDS
    if ttl and _last and time.monotonic() - _last[0] < ttl:
        return JsonResponse({"ok": _last[2], "checks": _last[1]}, status=200 if _last[2] else 503)
    results, ok = {}, True
    for name, check in CHECKS.items():
        started = time.monotonic()
        try:
            check()
            results[name] = "ok"
        except Exception:
            ok = False
            results[name] = "fail"
            log.exception(
                "readiness check %s failed after %.0f ms", name, (time.monotonic() - started) * 1000
            )
    _last = (time.monotonic(), results, ok)
    return JsonResponse({"ok": ok, "checks": results}, status=200 if ok else 503)
