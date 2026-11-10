"""JWT auth for WebSockets. Browsers can't set headers on WS, so the client
sends the access token as the first message: {"type":"auth","token":"..."}."""

from channels.db import database_sync_to_async
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def user_from_token(token: str):
    from apps.accounts.models import User

    try:
        payload = AccessToken(token)
        return User.objects.select_related("profile", "preferences").get(
            id=payload["user_id"], is_active=True
        )
    except (TokenError, KeyError, User.DoesNotExist):
        return None
