"""Outbound webhooks: emit(org, event, data) → one WebhookDelivery per subscribed webhook, delivered off the request.

Every delivery is an HTTPS POST through apps.learning.safe_fetch.post_json (URL re-vetted, DNS resolved and the public
IP pinned, no redirects, 10 s, 256 KB cap) with
  X-Aasan-Event, X-Aasan-Delivery, X-Aasan-Timestamp and X-Aasan-Signature: sha256=HMAC-SHA256(secret, f"{ts}.{body}")
A 2xx is success. A refused URL (FetchRefused: private address, http, bad port …) is dead at once; anything else is
retried with backoff and jitter, 5 tries in all. A webhook whose deliveries die 20 times in a row is switched off and
the organisation's admins are told. Payloads carry first names only — never emails."""

import hashlib
import hmac
import json
import logging
import random
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import OrgWebhook, WebhookDelivery

log = logging.getLogger(__name__)
MAX_TRIES = 5
DISABLE_AFTER = 20
BACKOFF_S = (30, 120, 600, 1800)  # before tries 2..5 (± 20 % jitter)


def first_name(user) -> str:
    from apps.orgs.api import _first

    return _first(user)[:40] if user else ""


def learner(user) -> dict:
    return {"user_id": user.id if user else None, "first_name": first_name(user)}


def _org_out(org) -> dict:
    return {"slug": org.slug, "name": org.display_name or org.name}


def emit(org, event: str, data: dict) -> list[int]:
    """Queue `event` for every active webhook of `org` subscribed to it. Returns the delivery ids."""
    hooks = [w for w in OrgWebhook.objects.filter(org=org, active=True) if event in (w.events or [])]
    if not hooks:
        return []
    body = {
        "id": str(uuid.uuid4()),
        "event": event,
        "created_at": timezone.now().isoformat(),
        "org": _org_out(org),
        "data": data,
    }
    ids = [
        WebhookDelivery.objects.create(webhook=w, event=event, payload=body, next_try_at=timezone.now()).id
        for w in hooks
    ]
    for i in ids:
        schedule(i)
    return ids


def schedule(delivery_id: int, countdown: int = 0) -> None:
    """Inline (tests: one attempt now); Celery after commit with Redis; else a thread after commit (dev).
    Retries are scheduled by `attempt` and also picked up by the `retry_due` beat job if a message is lost."""
    if getattr(settings, "LEARNING_JOBS_INLINE", False):
        if not countdown:
            attempt(delivery_id)
        return

    def go():
        if settings.REDIS_URL:
            from .tasks import deliver

            deliver.apply_async((delivery_id,), countdown=countdown)
        elif not countdown:
            from apps.learning.jobs import _thread

            _thread(attempt, delivery_id)

    transaction.on_commit(go)


def sign(secret: str, ts: str, body: str) -> str:
    return hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()


def _post(url: str, body: str, headers: dict):
    from apps.learning import safe_fetch

    return safe_fetch.post_json(url, body.encode(), headers=headers)


def _backoff(tries_done: int) -> int:
    base = BACKOFF_S[min(tries_done, len(BACKOFF_S)) - 1]
    return int(base * random.uniform(0.8, 1.2))


def attempt(delivery_id: int, *, retry: bool = True) -> WebhookDelivery | None:
    """One try. Claims the attempt under a row lock (parallel workers can't double-send), posts, records the outcome."""
    from apps.learning.safe_fetch import FetchFailed, FetchRefused
    from apps.providers.crypto import decrypt

    with transaction.atomic():
        d = (
            WebhookDelivery.objects.select_for_update(of=("self",))
            .select_related("webhook__org")
            .filter(pk=delivery_id)
            .first()
        )
        if not d or d.status in (WebhookDelivery.Status.OK, WebhookDelivery.Status.DEAD):
            return d
        if not d.webhook.active and d.event != "ping":
            d.status, d.last_error, d.next_try_at = WebhookDelivery.Status.DEAD, "webhook_disabled", None
            d.save(update_fields=["status", "last_error", "next_try_at"])
            return d
        d.attempt += 1
        d.next_try_at = None
        d.save(update_fields=["attempt", "next_try_at"])
    wh = d.webhook
    body = json.dumps(d.payload, ensure_ascii=False, separators=(",", ":"), default=str)
    ts = str(int(time.time()))
    headers = {
        "Content-Type": "application/json",
        "X-Aasan-Event": d.event,
        "X-Aasan-Delivery": str(d.id),
        "X-Aasan-Timestamp": ts,
        "X-Aasan-Signature": f"sha256={sign(decrypt(wh.secret_enc), ts, body)}",
    }
    code, error, terminal = None, "", False
    try:
        if wh.url and _own_host(wh.url):
            raise FetchRefused("own_host")
        r = _post(wh.url, body, headers)
        code = r.status
        if not 200 <= r.status < 300:
            error = f"http_{r.status}"
    except FetchRefused as e:
        error, terminal = e.code, True
    except FetchFailed as e:
        error = e.code
    except Exception:
        log.warning("webhook %s delivery %s failed", wh.id, d.id, exc_info=True)
        error = "error"
    return _finish(d.id, code, error, terminal or not retry or d.event == "ping")


def _finish(delivery_id: int, code, error: str, terminal: bool) -> WebhookDelivery:
    now = timezone.now()
    disabled = None
    with transaction.atomic():
        d = WebhookDelivery.objects.select_for_update(of=("self",)).get(pk=delivery_id)
        wh = OrgWebhook.objects.select_for_update().get(pk=d.webhook_id)
        d.response_status, d.last_error = code, error[:200]
        if not error:
            d.status, d.delivered_at = WebhookDelivery.Status.OK, now
            if d.event != "ping":
                wh.failures = 0
        elif terminal or d.attempt >= MAX_TRIES:
            d.status = WebhookDelivery.Status.DEAD
            if d.event != "ping":
                wh.failures += 1
                if wh.active and wh.failures >= DISABLE_AFTER:
                    wh.active, wh.disabled_reason, disabled = False, "too_many_failures", wh
        else:
            d.status = WebhookDelivery.Status.FAILED
            d.next_try_at = now + timedelta(seconds=_backoff(d.attempt))
        d.save()
        wh.save(update_fields=["failures", "active", "disabled_reason"])
    if d.status == WebhookDelivery.Status.FAILED:
        schedule(d.id, countdown=max(1, int((d.next_try_at - now).total_seconds())))
    if disabled:
        _tell_admins(disabled)
    return d


def _own_host(url: str) -> bool:
    """Webhooks must not point back at this service (it would call its own API with our signature)."""
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").rstrip(".").lower()
    own = {(urlsplit(settings.FRONTEND_URL).hostname or "").lower()}
    own |= {h.strip().lstrip(".").lower() for h in settings.ALLOWED_HOSTS if h.strip() and h.strip() != "*"}
    return bool(host) and any(host == h or host.endswith(f".{h}") for h in own if h)


def _tell_admins(wh: OrgWebhook) -> None:
    from apps.game.services import notify
    from apps.orgs.models import Membership

    for m in Membership.objects.filter(org_id=wh.org_id, role__in=["owner", "admin"]).select_related("user"):
        notify(
            m.user,
            "webhook",
            "⚠️ A webhook was switched off",
            "Deliveries kept failing, so Aasan stopped sending to it. Fix the receiver, then switch it back on.",
            f"/org/{wh.org.slug}",
        )


def retry_due() -> int:
    """Beat job: deliveries whose retry time passed (covers lost Celery messages and the dev thread mode)."""
    ids = list(
        WebhookDelivery.objects.filter(
            status=WebhookDelivery.Status.FAILED, next_try_at__lte=timezone.now()
        ).values_list("id", flat=True)[:500]
    )
    for i in ids:
        attempt(i)
    return len(ids)


def cleanup() -> int:
    days = int(getattr(settings, "WEBHOOK_RETENTION_DAYS", 30))
    n, _ = WebhookDelivery.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()
    return n
