"""Startup refusal of unsafe production settings.

Only a public site is held to this: one whose FRONTEND_URL is not on this machine. The prod-like docker stack on
http://localhost:8080 keeps working with its defaults, while a real deploy that forgot a key refuses to start.
"""

from urllib.parse import urlparse

# Compared against configured hosts; nothing binds to these.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}  # nosec B104
# LiveKit's built-in dev pair (`livekit-server --dev`). It is public, so anyone could mint tokens with it.
LIVEKIT_DEV_KEY, LIVEKIT_DEV_SECRET = "devkey", "secret"


def is_local_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def weak_livekit_keys(key: str, secret: str) -> bool:
    return key == LIVEKIT_DEV_KEY or secret == LIVEKIT_DEV_SECRET or len(secret) < 32


def production_problems(
    *,
    frontend_url: str,
    allowed_hosts: list[str],
    secret_key: str,
    secrets_key: str,
    livekit_url: str,
    livekit_public_url: str,
    livekit_key: str,
    livekit_secret: str,
    sentry_dsn: str = "",
    sentry_optional: bool = False,
    env_file_mode: int | None = None,
) -> list[str]:
    """What is unsafe about these settings for a public site (empty when fine or when the site is local)."""
    problems = []
    if (
        livekit_url
        and not is_local_url(livekit_public_url)
        and weak_livekit_keys(livekit_key, livekit_secret)
    ):
        problems.append(
            "LIVEKIT_API_KEY/LIVEKIT_API_SECRET are LiveKit's public dev pair (or the secret is under 32 characters). "
            "Set your own pair (e.g. `openssl rand -hex 32`) for both the API and the livekit server."
        )
    if is_local_url(frontend_url):
        return problems
    if urlparse(frontend_url).scheme != "https":
        problems.append(f"FRONTEND_URL must be https:// on a public site (got {frontend_url}).")
    if all(h.strip() in LOCAL_HOSTS for h in allowed_hosts if h.strip()):
        problems.append("DJANGO_ALLOWED_HOSTS lists only local hosts; add the public domain.")
    if len(secret_key) < 50:
        problems.append(
            "DJANGO_SECRET_KEY is shorter than 50 characters; generate one with `manage.py setup_env`."
        )
    if not secrets_key:
        problems.append("AASAN_SECRETS_KEY is not set; stored provider keys can't be encrypted.")
    if not sentry_dsn and not sentry_optional:
        problems.append(
            "SENTRY_DSN is not set, so nobody hears about server errors. Set it (sentry.io or self-hosted GlitchTip), "
            "or set SENTRY_OPTIONAL=1 to run without error reporting on purpose."
        )
    if env_file_mode is not None and env_file_mode & 0o077:
        problems.append(
            f"api/.env is readable by other users (mode {env_file_mode & 0o777:o}); run `chmod 600 api/.env`."
        )
    return problems
