from rest_framework_simplejwt.authentication import JWTAuthentication

from llm.usage import current_user_id


class MeteredJWTAuthentication(JWTAuthentication):
    """Standard JWT auth that also tags this request's AI usage with the user (reset for anonymous requests)."""

    def authenticate(self, request):
        result = super().authenticate(request)
        current_user_id.set(result[0].id if result else None)
        return result
