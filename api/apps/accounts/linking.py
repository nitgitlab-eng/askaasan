"""Sign in / sign up through an external identity (Google, an organisation's SSO): find the account by the provider's
subject, else link it to an existing verified account with the same email, else create one.

Shared by `views.google_login` and `apps.orgs.sso` so both keep the same squatting rule (see AccountUnverified)."""

from django.db import transaction

from .models import User

SUBJECT_FIELDS = ("google_sub", "sso_subject")


class AccountUnverified(Exception):
    """An account with this email exists but its owner never proved the inbox. Anyone can register a password account
    for an address they don't own; linking an external identity to it would hand the real owner a session the squatter
    also holds. The owner must first prove the inbox (password reset), which also ends the squatter's sessions.
    Callers answer 409 `account_unverified`."""


def link_or_create(
    email: str, subject_field: str, subject: str, name: str = "", language: str | None = None
) -> tuple[User, bool]:
    """→ (user, created). `email` must already be verified by the identity provider. Raises AccountUnverified."""
    from .serializers import UI_LANGUAGES

    if subject_field not in SUBJECT_FIELDS:
        raise ValueError(subject_field)
    email = email.lower()
    with transaction.atomic():
        user = User.objects.filter(**{subject_field: subject}).first()
        if user is None and (user := User.objects.filter(email=email).first()) and not user.email_verified:
            raise AccountUnverified
        created = user is None
        if created:
            user = User.objects.create_user(email)
            user.profile.display_name = (name or "")[:80]
            user.profile.language = language if language in UI_LANGUAGES else "en"
            user.profile.save()
        setattr(user, subject_field, subject)
        user.email_verified = True
        user.save(update_fields=[subject_field, "email_verified"])
        from apps.game.services import pay_referral

        pay_referral(user)
    return user, created
