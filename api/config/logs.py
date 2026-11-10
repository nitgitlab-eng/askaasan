"""One-line structured logs on stdout, tagged with the current request id.

LOG_FORMAT=json (the default with DEBUG off) prints one JSON object per line, which log shippers parse as is;
LOG_FORMAT=plain (the default with DEBUG on) prints a readable line for local development."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

# Set by config.middleware.RequestId for the duration of a request ("-" outside one: Celery, management commands).
request_id: ContextVar[str] = ContextVar("request_id", default="-")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """{"ts", "level", "logger", "msg", "request_id", plus "exc" and any `extra={...}` fields}, on one line."""

    _STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
        "message",
        "asctime",
        "request_id",
    }

    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for key, value in vars(record).items():
            if key not in self._STANDARD and not key.startswith("_"):
                out[key] = value if isinstance(value, (str, int, float, bool, type(None))) else str(value)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def build_logging(level: str, fmt: str) -> dict:
    """The LOGGING dict for settings.py. Django's default handlers are reproduced (staff error emails with DEBUG off,
    the runserver access log) so nothing is printed twice."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": "config.logs.RequestIdFilter"},
            "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
        },
        "formatters": {
            "json": {"()": "config.logs.JsonFormatter"},
            "plain": {"format": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"},
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": fmt,
                "filters": ["request_id"],
            },
            "mail_admins": {
                "level": "ERROR",
                "filters": ["require_debug_false"],
                "class": "django.utils.log.AdminEmailHandler",
            },
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            "django": {"handlers": ["mail_admins"], "level": "INFO", "propagate": True},
            "django.server": {"handlers": ["stdout"], "level": "INFO", "propagate": False},
        },
    }
