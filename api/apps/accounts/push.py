"""Web push (VAPID): store each device's PushSubscription and send short notifications to it.

`send()` is the one entry point the reminder paths call. It is a no-op when push is off (no VAPID keys or
WEBPUSH_ENABLED=false), when the learner turned that kind off, or when they have no subscribed device; otherwise it
queues `tasks.push_deliver`. Payloads carry only a title, a short body and an in-app path: never codes, tokens or
anything secret (push services and lock screens can see them).

Security: an endpoint must be https on a known browser push service (WEBPUSH_ENDPOINT_HOSTS) so a crafted endpoint
can't make the server call an internal address; keys are checked as base64url of the right length; at most
MAX_PER_USER devices per account (oldest dropped); dead endpoints (404/410) are deleted at once and flaky ones after
MAX_FAILURES failures in a row.

The payload's `id` is a random per-push token (PushLog), not a secret: it only lets the service worker report "this
notification was tapped" (POST /api/users/push/opened/) so ignored reminders can be sent less often (cadence.py)."""

import base64
import binascii
import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)

MAX_ENDPOINT = 1000
MAX_FAILURES = 5
TTL = 3600  # a reminder older than an hour is not worth showing

# kind → the notification preference that switches it off ("test" is always allowed: the learner asked for it).
KIND_PREF = {
    "study": "push_study",
    "winback": "push_study",
    "streak": "push_streak",
    "reviews": "push_reviews",
    "workshops": "push_workshops",
    "teacher": "push_teacher",
    "plan": "push_plan",
    "test": None,
}


def enabled() -> bool:
    return bool(
        settings.WEBPUSH_ENABLED and settings.WEBPUSH_VAPID_PUBLIC_KEY and settings.WEBPUSH_VAPID_PRIVATE_KEY
    )


def endpoint_allowed(endpoint: str) -> bool:
    if not isinstance(endpoint, str) or not endpoint or len(endpoint) > MAX_ENDPOINT:
        return False
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password or port not in (None, 443):
        return False
    for allowed in settings.WEBPUSH_ENDPOINT_HOSTS:
        if allowed.startswith("*."):
            if host.endswith(allowed[1:]) and len(host) > len(allowed) - 1:
                return True
        elif host == allowed:
            return True
    return False


def _b64url_len(value, size: int) -> bool:
    """`value` is unpadded or padded base64url that decodes to exactly `size` bytes."""
    if not isinstance(value, str) or not value or len(value) > 200:
        return False
    if not all(c.isalnum() or c in "-_=" for c in value):
        return False
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError):
        return False
    return len(raw) == size


def valid_keys(p256dh, auth) -> bool:
    # p256dh: an uncompressed P-256 point (65 bytes); auth: a 16-byte secret.
    return _b64url_len(p256dh, 65) and _b64url_len(auth, 16)


def subscribe(user, endpoint: str, p256dh: str, auth: str, user_agent: str = ""):
    """Save (or move to this account) a device's subscription, keeping at most MAX_PER_USER per account."""
    from .models import PushSubscription

    sub, _ = PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": user,
            "p256dh": p256dh,
            "auth": auth,
            "user_agent": (user_agent or "")[:200],
            "failures": 0,
        },
    )
    keep = PushSubscription.objects.filter(user=user).order_by("-created_at", "-id")[
        : PushSubscription.MAX_PER_USER
    ]
    PushSubscription.objects.filter(user=user).exclude(
        pk__in=list(keep.values_list("pk", flat=True))
    ).delete()
    return sub


def _wants(user, kind: str) -> bool:
    if kind not in KIND_PREF:
        return False
    pref = KIND_PREF[kind]
    if pref is None:
        return True
    from .preferences import upgrade

    return bool(upgrade(user.preferences.data)["notifications"].get(pref, True))


def _path(url: str) -> str:
    """Only in-app paths: the service worker opens them on our own origin."""
    url = (url or "/").strip()
    if not url.startswith("/") or url.startswith("//") or "\\" in url:
        return "/"
    return url[:200]


def send(
    user, kind: str, title: str, body: str = "", url: str = "/", moment: str = "", variant: str = ""
) -> bool:
    """Queue a push to every device of `user`. Never raises: a push problem must not break the caller.

    Reminder kinds also pass the back-off gate (cadence.allowed). Every queued push is logged (PushLog) with a
    random token the service worker reports back when the notification is tapped; `moment`/`variant` record which
    catalog message it was (voice.py)."""
    try:
        if not enabled() or not _wants(user, kind):
            return False
        from . import cadence
        from .models import PushLog, PushSubscription

        if not PushSubscription.objects.filter(user=user).exists():
            return False
        if not cadence.allowed(user, kind, moment):
            return False
        entry = cadence.log_push(user, kind, moment, variant)
        payload = {
            "title": (title or "Aasan")[:120],
            "body": (body or "")[:240],
            "url": _path(url),
            "kind": kind,
            "tag": f"aasan-{kind}",
            "id": entry.token,
        }
        from .tasks import push_deliver

        try:
            push_deliver.delay(user.id, payload)
        except Exception:
            PushLog.objects.filter(pk=entry.pk).delete()  # never queued: don't count it as ignored
            raise
        return True
    except Exception:
        log.exception("push: queueing a %s push for user %s failed", kind, getattr(user, "id", None))
        return False


def _status_of(exc) -> int | None:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


def deliver(user_id: int, payload: dict) -> int:
    """Send `payload` to each of the user's devices. → how many accepted it."""
    if not enabled():
        return 0
    from pywebpush import WebPushException, webpush  # lazy: the API boots without the library

    from .models import PushSubscription

    data = json.dumps(payload, ensure_ascii=False)
    sent = 0
    for sub in PushSubscription.objects.filter(user_id=user_id):
        if not endpoint_allowed(sub.endpoint):  # allowlist narrowed since it was saved
            sub.delete()
            continue
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=data,
                vapid_private_key=settings.WEBPUSH_VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.WEBPUSH_VAPID_SUBJECT},
                ttl=TTL,
                timeout=10,
            )
        except WebPushException as e:
            if _status_of(e) in (404, 410):  # the browser dropped this subscription
                sub.delete()
                continue
            _failed(sub, e)
            continue
        except Exception as e:  # noqa: BLE001 — network trouble: count it, try again next time
            _failed(sub, e)
            continue
        PushSubscription.objects.filter(pk=sub.pk).update(last_used_at=timezone.now(), failures=0)
        sent += 1
    return sent


def _failed(sub, exc) -> None:
    from .models import PushSubscription

    log.warning("push: delivery to subscription %s failed (%s)", sub.pk, type(exc).__name__)
    if sub.failures + 1 >= MAX_FAILURES:
        sub.delete()
    else:
        PushSubscription.objects.filter(pk=sub.pk).update(failures=sub.failures + 1)
