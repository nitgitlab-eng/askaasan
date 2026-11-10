"""Platform-wide feature switches (admin console → Lesson media). All off by default."""

from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.staff import AdminSection

from .models import PlatformSettings

FEATURES = ("podcast", "explainer", "listen")


def flags() -> dict[str, bool]:
    s = PlatformSettings.load()
    return {f: bool(getattr(s, f"{f}_enabled")) for f in FEATURES}


def enabled(feature: str) -> bool:
    return flags()[feature]


def refuse_if_off(feature: str) -> Response | None:
    """403 {"code": "feature_off"} when the admin has switched this feature off."""
    if enabled(feature):
        return None
    return Response({"code": "feature_off", "feature": feature}, status=status.HTTP_403_FORBIDDEN)


class FeaturesPatch(serializers.Serializer):
    podcast = serializers.BooleanField(required=False)
    explainer = serializers.BooleanField(required=False)
    listen = serializers.BooleanField(required=False)


def _out(s: PlatformSettings) -> dict:
    return {
        **{f: bool(getattr(s, f"{f}_enabled")) for f in FEATURES},
        "updated_at": s.updated_at if s.pk and s.updated_at else None,
        "updated_by": s.updated_by.email if s.updated_by_id else None,
    }


@api_view(["GET", "PATCH"])
@permission_classes([AdminSection])
def admin_features(request):
    """GET → switches. PATCH {podcast?, explainer?, listen?} → saved switches (audited by AdminAudit)."""
    s = PlatformSettings.load()
    if request.method == "PATCH":
        ser = FeaturesPatch(data=request.data)
        ser.is_valid(raise_exception=True)
        for f, v in ser.validated_data.items():
            setattr(s, f"{f}_enabled", v)
        s.updated_by = request.user
        s.save()
    return Response(_out(s))
