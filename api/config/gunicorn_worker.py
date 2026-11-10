"""Uvicorn worker for gunicorn with Aasan's WebSocket and proxy settings (gunicorn's CLI can't pass these)."""

import os

from uvicorn_worker import UvicornWorker


class AasanUvicornWorker(UvicornWorker):
    CONFIG_KWARGS = {
        **UvicornWorker.CONFIG_KWARGS,
        "lifespan": "off",  # Django has no lifespan handler
        # Django reads the client IP from X-Forwarded-For itself (DJANGO_NUM_PROXIES); uvicorn must not rewrite it.
        "proxy_headers": False,
        # Pings keep idle sockets open through proxies and drop dead clients (a phone that lost signal).
        "ws_ping_interval": float(os.environ.get("WS_PING_INTERVAL", "20")),
        "ws_ping_timeout": float(os.environ.get("WS_PING_TIMEOUT", "20")),
        "ws_max_size": 4 * 1024 * 1024,  # Live Class camera snapshots arrive over the socket
        "timeout_keep_alive": 75,  # longer than nginx's upstream keepalive_timeout (60 s)
    }
