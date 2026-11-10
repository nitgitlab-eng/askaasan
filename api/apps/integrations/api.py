"""Cockpit → Integrations (org owners/admins): API keys and webhooks, under /api/orgs/<slug>/integrations/.

GET/POST   keys/                                 list / create (the raw key is returned once; max 10 active)
DELETE     keys/<id>/                            revoke
GET/POST   webhooks/                             list / create (https URL vetted; the signing secret is shown once)
PATCH/DEL  webhooks/<id>/                        {url?, events?, active?} / delete
POST       webhooks/<id>/rotate-secret/          new signing secret (shown once)
POST       webhooks/<id>/test/                   send a `ping` now (10/hour)
GET        webhooks/<id>/deliveries/             paged delivery log
POST       webhooks/<id>/deliveries/<did>/redeliver/
"""

import secrets

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.accounts.admin_paging import paged
from apps.orgs.perms import require

from . import events
from .models import EVENTS, SCOPES, OrgApiKey, OrgWebhook, WebhookDelivery, hash_key, new_raw_key

MAX_KEYS = 10
MAX_WEBHOOKS = 10


def _key_out(k: OrgApiKey) -> dict:
    return {
        "id": k.id,
        "name": k.name,
        "prefix": k.prefix,
        "scopes": k.scopes,
        "created_at": k.created_at,
        "created_by": k.created_by.email if k.created_by_id else None,
        "last_used_at": k.last_used_at,
        "revoked_at": k.revoked_at,
    }


class KeyIn(serializers.Serializer):
    name = serializers.CharField(min_length=1, max_length=80)
    scopes = serializers.ListField(
        child=serializers.ChoiceField(choices=SCOPES), min_length=1, max_length=len(SCOPES)
    )


@api_view(["GET", "POST"])
def keys(request, slug):
    me = require(request.user, slug, "admin")
    qs = OrgApiKey.objects.filter(org=me.org).select_related("created_by")
    if request.method == "GET":
        return Response({"keys": [_key_out(k) for k in qs[:50]], "scopes": list(SCOPES)})
    ser = KeyIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if qs.filter(revoked_at__isnull=True).count() >= MAX_KEYS:
        return Response({"code": "too_many_keys"}, status=status.HTTP_409_CONFLICT)
    raw = new_raw_key()
    k = OrgApiKey.objects.create(
        org=me.org,
        name=ser.validated_data["name"].strip(),
        prefix=raw[:11],
        key_hash=hash_key(raw),
        scopes=sorted(set(ser.validated_data["scopes"])),
        created_by=request.user,
    )
    return Response({**_key_out(k), "key": raw}, status=status.HTTP_201_CREATED)  # shown once, never again


@api_view(["DELETE"])
def key_detail(request, slug, pk):
    me = require(request.user, slug, "admin")
    k = get_object_or_404(OrgApiKey, pk=pk, org=me.org)
    if not k.revoked_at:
        k.revoked_at = timezone.now()
        k.save(update_fields=["revoked_at"])
    return Response(status=status.HTTP_204_NO_CONTENT)


# ── Webhooks ──────────────────────────────────────────────────────────


def vet_url(url: str) -> str | None:
    """None when the URL may be used; else an error code. https only, public DNS answers only, never our own host."""
    from apps.learning.safe_fetch import FetchFailed, FetchRefused, check_url, safe_ip

    try:
        host, _ = check_url(url)
        if events._own_host(url):
            return "own_host"
        safe_ip(host)
    except FetchRefused as e:
        return e.code
    except FetchFailed as e:
        return e.code
    return None


def _hook_out(w: OrgWebhook) -> dict:
    last = w.deliveries.order_by("-created_at", "-id").first()
    return {
        "id": w.id,
        "url": w.url,
        "events": w.events,
        "active": w.active,
        "failures": w.failures,
        "disabled_reason": w.disabled_reason,
        "created_at": w.created_at,
        "last_delivery": {"status": last.status, "event": last.event, "at": last.created_at}
        if last
        else None,
    }


class HookIn(serializers.Serializer):
    url = serializers.CharField(max_length=500)
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=EVENTS), min_length=1, max_length=len(EVENTS)
    )


def _secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


@api_view(["GET", "POST"])
def webhooks(request, slug):
    from apps.providers.crypto import encrypt

    me = require(request.user, slug, "admin")
    qs = OrgWebhook.objects.filter(org=me.org)
    if request.method == "GET":
        return Response({"webhooks": [_hook_out(w) for w in qs], "events": list(EVENTS)})
    ser = HookIn(data=request.data)
    ser.is_valid(raise_exception=True)
    if qs.count() >= MAX_WEBHOOKS:
        return Response({"code": "too_many_webhooks"}, status=status.HTTP_409_CONFLICT)
    url = ser.validated_data["url"].strip()
    if code := vet_url(url):
        return Response({"code": "bad_url", "reason": code}, status=status.HTTP_400_BAD_REQUEST)
    secret = _secret()
    w = OrgWebhook.objects.create(
        org=me.org,
        url=url,
        secret_enc=encrypt(secret),
        events=sorted(set(ser.validated_data["events"])),
        created_by=request.user,
    )
    return Response({**_hook_out(w), "secret": secret}, status=status.HTTP_201_CREATED)  # shown once


@api_view(["PATCH", "DELETE"])
def webhook_detail(request, slug, pk):
    me = require(request.user, slug, "admin")
    w = get_object_or_404(OrgWebhook, pk=pk, org=me.org)
    if request.method == "DELETE":
        w.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    data = request.data if isinstance(request.data, dict) else {}
    fields = []
    if "url" in data:
        url = str(data.get("url") or "").strip()[:500]
        if code := vet_url(url):
            return Response({"code": "bad_url", "reason": code}, status=status.HTTP_400_BAD_REQUEST)
        w.url = url
        fields.append("url")
    if "events" in data:
        evs = data.get("events")
        if not isinstance(evs, list) or not evs or not set(evs) <= set(EVENTS):
            return Response({"code": "bad_events"}, status=status.HTTP_400_BAD_REQUEST)
        w.events = sorted(set(evs))
        fields.append("events")
    if "active" in data:
        if not isinstance(data["active"], bool):
            return Response({"code": "bad_active"}, status=status.HTTP_400_BAD_REQUEST)
        w.active = data["active"]
        if w.active:  # switched back on: a fresh start
            w.failures, w.disabled_reason = 0, ""
            fields += ["failures", "disabled_reason"]
        fields.append("active")
    if fields:
        w.save(update_fields=fields)
    return Response(_hook_out(w))


@api_view(["POST"])
def webhook_rotate(request, slug, pk):
    from apps.providers.crypto import encrypt

    me = require(request.user, slug, "admin")
    w = get_object_or_404(OrgWebhook, pk=pk, org=me.org)
    secret = _secret()
    w.secret_enc = encrypt(secret)
    w.save(update_fields=["secret_enc"])
    return Response({**_hook_out(w), "secret": secret})


class PingThrottle(UserRateThrottle):
    scope, rate = "webhook_test", "10/hour"


@api_view(["POST"])
@throttle_classes([PingThrottle])
def webhook_test(request, slug, pk):
    me = require(request.user, slug, "admin")
    w = get_object_or_404(OrgWebhook, pk=pk, org=me.org)
    body = {
        "id": secrets.token_hex(16),
        "event": "ping",
        "created_at": timezone.now().isoformat(),
        "org": events._org_out(me.org),
        "data": {"message": "Test delivery from Aasan"},
    }
    d = WebhookDelivery.objects.create(webhook=w, event="ping", payload=body)
    d = events.attempt(d.id)  # one try, now, so the admin sees the result
    return Response(_delivery_out(d))


def _delivery_out(d: WebhookDelivery) -> dict:
    return {
        "id": d.id,
        "event": d.event,
        "status": d.status,
        "attempt": d.attempt,
        "response_status": d.response_status,
        "last_error": d.last_error,
        "next_try_at": d.next_try_at,
        "created_at": d.created_at,
        "delivered_at": d.delivered_at,
    }


@api_view(["GET"])
def webhook_deliveries(request, slug, pk):
    me = require(request.user, slug, "admin")
    w = get_object_or_404(OrgWebhook, pk=pk, org=me.org)
    return paged(request, w.deliveries.all(), _delivery_out, name=f"webhook-{w.id}-deliveries")


@api_view(["POST"])
def webhook_redeliver(request, slug, pk, did):
    me = require(request.user, slug, "admin")
    w = get_object_or_404(OrgWebhook, pk=pk, org=me.org)
    old = get_object_or_404(WebhookDelivery, pk=did, webhook=w)
    if old.event == "ping":
        return Response({"code": "use_test"}, status=status.HTTP_400_BAD_REQUEST)
    d = WebhookDelivery.objects.create(
        webhook=w, event=old.event, payload=old.payload, next_try_at=timezone.now()
    )
    events.schedule(d.id)  # same payload id, so receivers can de-duplicate
    d.refresh_from_db()
    return Response(_delivery_out(d), status=status.HTTP_201_CREATED)
