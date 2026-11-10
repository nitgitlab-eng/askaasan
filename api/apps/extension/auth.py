"""`Authorization: AasanExt <token>` — accepted ONLY by the /api/ext/ views that list this class explicitly.
Every other API route keeps the default JWT auth, which ignores this header, so a stolen extension token
can't read or change anything outside the extension's narrow surface."""

from datetime import timedelta

from django.utils import timezone
from rest_framework import authentication, exceptions

from llm.usage import current_user_id

from .models import ExtensionToken, token_hash

KEYWORD = "AasanExt"


class ExtensionTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        parts = authentication.get_authorization_header(request).split()
        if not parts or parts[0].decode(errors="ignore") != KEYWORD:
            return None
        if len(parts) != 2 or len(parts[1]) > 200:
            raise exceptions.AuthenticationFailed("bad_token")
        tok = (
            ExtensionToken.objects.select_related("user")
            .filter(token_hash=token_hash(parts[1].decode(errors="ignore")), revoked_at__isnull=True)
            .first()
        )
        if not tok or not tok.user.is_active:
            raise exceptions.AuthenticationFailed("bad_token")
        now = timezone.now()
        if not tok.last_used_at or now - tok.last_used_at > timedelta(minutes=1):
            ExtensionToken.objects.filter(pk=tok.pk).update(last_used_at=now)
        current_user_id.set(tok.user_id)  # tag this request's AI usage with the learner
        return tok.user, tok

    def authenticate_header(self, request):
        return KEYWORD
