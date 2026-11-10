import logging
import re
import time
import uuid

from django.conf import settings

from llm.usage import current_user_id

from .logs import request_id

log = logging.getLogger("aasan.request")
_VALID_ID = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


class RequestId:
    """Tag every request with an id: the caller's X-Request-ID when it is well formed (nginx sets one), else a new one.
    The id goes into every log line of the request and back to the client in X-Request-ID. Requests slower than
    SLOW_REQUEST_MS (default 1000) are logged as a warning."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get("HTTP_X_REQUEST_ID", "")
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        request.request_id = rid
        token = request_id.set(rid)
        started = time.monotonic()
        try:
            response = self.get_response(request)
            response["X-Request-ID"] = rid
            ms = (time.monotonic() - started) * 1000
            if ms > settings.SLOW_REQUEST_MS:
                log.warning(
                    "slow request %s %s -> %s in %.0f ms",
                    request.method,
                    request.path,
                    response.status_code,
                    ms,
                    extra={"duration_ms": round(ms), "status": response.status_code, "path": request.path},
                )
            return response
        finally:
            request_id.reset(token)


class HealthCheck:
    """Answers /api/health/ (liveness), /api/health/ready/ (readiness) and /api/metrics/ before host validation, the HTTPS redirect,
    CORS and sessions, so the container and load-balancer probes work whatever DJANGO_ALLOWED_HOSTS says."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from . import health

        if request.path == "/api/health/":
            return health.live(request)
        if request.path == "/api/health/ready/":
            return health.ready(request)
        if (
            request.path == "/api/metrics/"
        ):  # Prometheus scrapes http://api:8000 inside Docker (token-protected)
            from .metrics import metrics

            return metrics(request)
        return self.get_response(request)


class ResetUsageUser:
    """Clear the AI-usage attribution at the start of every request (threads are reused between requests)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        current_user_id.set(None)
        return self.get_response(request)
