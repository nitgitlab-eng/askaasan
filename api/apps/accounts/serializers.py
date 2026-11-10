from django.contrib.auth import password_validation
from pydantic import ValidationError as PydanticError
from rest_framework import serializers

from .models import Profile, User
from .preferences import Preferences, deep_merge, upgrade


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    display_name = serializers.CharField(max_length=80, required=False, allow_blank=True)
    language = serializers.ChoiceField(
        choices=["en", "ta", "hi", "te", "kn", "ml", "bn", "mr", "gu"], default="en"
    )  # = UI_LANGUAGES
    ref = serializers.CharField(max_length=12, required=False, allow_blank=True)
    accept_terms = serializers.BooleanField(required=False, default=False)
    age_band = serializers.ChoiceField(choices=["adult", "minor"], required=False)
    guardian_email = serializers.EmailField(required=False, allow_blank=True)

    def validate_email(self, value):
        value = value.lower()
        if value.endswith(
            ".invalid"
        ):  # reserved TLD (RFC 2606); system accounts such as archive@aasan.invalid live there
            raise serializers.ValidationError("email_reserved")
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("email_taken")
        return value

    def validate(self, attrs):
        password_validation.validate_password(attrs["password"], User(email=attrs["email"]))
        if attrs.get("accept_terms") and attrs.get("age_band") == "minor" and not attrs.get("guardian_email"):
            raise serializers.ValidationError({"guardian_email": "guardian_required"})
        return attrs

    def create(self, data):
        user = User.objects.create_user(data["email"], data["password"])
        user.profile.display_name = data.get("display_name", "")
        user.profile.language = data["language"]
        user.profile.save()
        if data.get("accept_terms") and data.get("age_band"):
            from apps.legal.api import record_consent

            record_consent(user, data["age_band"], data.get("guardian_email", ""))
        if data.get("ref"):
            from apps.game.services import credit_referral

            credit_referral(user, data["ref"].strip().upper())
        return user


UI_LANGUAGES = ("en", "ta", "hi", "te", "kn", "ml", "bn", "mr", "gu")


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = [
            "display_name",
            "language",
            "domain",
            "goals",
            "skills",
            "level",
            "onboarding_completed",
            "avatar",
        ]

    def validate_language(self, v):
        if v not in UI_LANGUAGES:
            raise serializers.ValidationError("unsupported_language")
        return v

    def validate_goals(self, v):
        # Goals are read into the AI tutor's instructions: keep them a short list of short strings.
        if not isinstance(v, list) or len(v) > 10 or not all(isinstance(g, str) for g in v):
            raise serializers.ValidationError("goals_invalid")
        v = [g.strip() for g in v if g.strip()]
        if any(len(g) > 200 for g in v):  # same cap as the onboarding interview (paths/api.py)
            raise serializers.ValidationError("goal_too_long")
        return v


class MeSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()
    preferences = serializers.SerializerMethodField()
    has_password = serializers.SerializerMethodField()
    consent = serializers.SerializerMethodField()
    staff_roles = serializers.SerializerMethodField()  # admin console sections this person may use
    features = serializers.SerializerMethodField()  # platform switches (lesson podcast, explainer, Listen)
    can_author = serializers.BooleanField(
        read_only=True
    )  # creator, staff, or teacher/admin of a school (Creator Lab)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "email_verified",
            "is_staff",
            "staff_roles",
            "is_creator",
            "can_author",
            "has_password",
            "profile",
            "preferences",
            "consent",
            "features",
        ]
        read_only_fields = fields

    def get_features(self, user):
        from apps.providers.features import flags

        return flags()

    def get_preferences(self, user):
        return upgrade(user.preferences.data)

    def get_staff_roles(self, user):
        from .staff import roles_of

        return sorted(roles_of(user))

    def get_has_password(self, user):
        return user.has_usable_password()

    def get_consent(self, user):
        from apps.legal.models import TERMS_VERSION

        from .guardian import consent_state

        return {
            "required": user.terms_version != TERMS_VERSION,
            "version": TERMS_VERSION,
            "age_band": user.age_band or None,
            "guardian": consent_state(user),  # pending | given | objected | None (adults)
        }


def validate_preferences_patch(current: dict, patch: dict) -> dict:
    """Merge a partial patch over stored prefs and validate the full result."""
    merged = deep_merge(upgrade(current), patch)
    try:
        return Preferences.model_validate(merged).model_dump()
    except PydanticError as exc:
        raise serializers.ValidationError(
            {".".join(str(p) for p in e["loc"]): e["msg"] for e in exc.errors()}
        ) from exc
