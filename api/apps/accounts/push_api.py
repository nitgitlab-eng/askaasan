"""Web push endpoints: is push available, add or remove this device, send a test, report a tapped notification and
resume backed-off reminders."""

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

from . import cadence, push
from .models import PushSubscription


class PushThrottle(UserRateThrottle):
    scope = "push"  # 30/hour per account (settings.REST_FRAMEWORK)


class PushOpenThrottle(AnonRateThrottle):
    scope = "push_open"  # 60/hour per IP: the service worker's "tapped" ping carries no credentials


@api_view(["GET"])
def push_status(request):
    return Response(
        {
            "enabled": push.enabled(),
            "public_key": settings.WEBPUSH_VAPID_PUBLIC_KEY if push.enabled() else "",
            "subscribed": PushSubscription.objects.filter(user=request.user).exists(),
            "devices": PushSubscription.objects.filter(user=request.user).count(),
            "reminders": cadence.status(request.user),
        }
    )


@api_view(["POST"])
@authentication_classes([])
@permission_classes([permissions.AllowAny])
@throttle_classes([PushOpenThrottle])
def push_opened(request):
    """The service worker saw a notification tapped. It has no session, so the push's random token is the only
    input; the answer is always 204 so the endpoint reveals nothing about which tokens exist."""
    data = request.data if isinstance(request.data, dict) else {}
    cadence.mark_opened(data.get("id"))
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@throttle_classes([PushThrottle])
def push_resume(request):
    cadence.resume(request.user.id, manual=True)
    return Response({"reminders": cadence.status(request.user)})


@api_view(["POST", "DELETE"])
@throttle_classes([PushThrottle])
def push_subscriptions(request):
    data = request.data if isinstance(request.data, dict) else {}
    endpoint = data.get("endpoint")
    if request.method == "DELETE":
        if not isinstance(endpoint, str) or not endpoint:
            return Response({"code": "endpoint_required"}, status=status.HTTP_400_BAD_REQUEST)
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    if not push.enabled():
        return Response({"code": "push_disabled"}, status=status.HTTP_400_BAD_REQUEST)
    if not push.endpoint_allowed(endpoint):
        return Response({"code": "bad_endpoint"}, status=status.HTTP_400_BAD_REQUEST)
    keys = data.get("keys") if isinstance(data.get("keys"), dict) else {}
    if not push.valid_keys(keys.get("p256dh"), keys.get("auth")):
        return Response({"code": "bad_keys"}, status=status.HTTP_400_BAD_REQUEST)
    push.subscribe(
        request.user, endpoint, keys["p256dh"], keys["auth"], request.headers.get("User-Agent", "")
    )
    return Response(
        {"subscribed": True, "devices": PushSubscription.objects.filter(user=request.user).count()},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@throttle_classes([PushThrottle])
def push_test(request):
    if not push.enabled():
        return Response({"code": "push_disabled"}, status=status.HTTP_400_BAD_REQUEST)
    if not PushSubscription.objects.filter(user=request.user).exists():
        return Response({"code": "not_subscribed"}, status=status.HTTP_400_BAD_REQUEST)
    ta = getattr(request.user.profile, "language", "en") == "ta"
    push.send(
        request.user,
        "test",
        "Aasan 🦜",
        "அறிவிப்புகள் வேலை செய்கின்றன!" if ta else "Notifications are working!",
        "/account",
    )
    return Response({"queued": True})
