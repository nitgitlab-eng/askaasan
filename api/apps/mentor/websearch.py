"""When a learner-facing reply may search the web, and the per-learner daily cap (cache, like the throttles).

Used by every AI conversation a learner can speak to: the mentor socket (chat, Ask Aasan voice, Lesson Ask, Documents
on request), Live Class, role-play and workshops. Role-play and workshops get extra rules (search_note kind): the
character stays in the scene, and a workshop host never looks up or gives away exercise answers. Learn with Kili is
a structured text lesson (no voice) and doesn't search."""

import re

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

# Documents chat answers from the learner's notes; it searches only when they ask for the web.
_ASKS_FOR_WEB = re.compile(
    r"(?i)\b(search|google|look (it )?up|check)\b.{0,30}\b(web|online|internet|google)\b|"
    r"\b(on|from) the (web|internet)\b|\bonline\b|\blatest\b|\bcurrent\b|\btoday'?s?\b|இணைய|இன்று|சமீபத்திய"
)


def asks_for_web(text: str) -> bool:
    return bool(_ASKS_FOR_WEB.search(text or ""))


def _key(user_id: int) -> str:
    # The daily allowance resets at midnight India time (the server clock is UTC).
    return f"websearch:{user_id}:{timezone.localdate().isoformat()}"


def search_allowed(user) -> bool:
    if not settings.MENTOR_WEB_SEARCH:
        return False
    return (cache.get(_key(user.pk)) or 0) < settings.MENTOR_WEB_SEARCH_PER_DAY


def count_search(user) -> None:
    """Called once per reply that really searched."""
    key = _key(user.pk)
    if not cache.add(key, 1, timeout=60 * 60 * 26):
        try:
            cache.incr(key)
        except ValueError:  # expired between add and incr
            cache.set(key, 1, timeout=60 * 60 * 26)


def note_search(user, searched: bool, final) -> bool:
    """Count a reply that searched once. Some providers (Gemini) send no "searching" event, only sources at the end."""
    if not searched and final is not None and getattr(final, "sources", None):
        count_search(user)
        return True
    return searched
