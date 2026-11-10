"""Security counters: login lockouts, OTP codes and tries, mail caps, code-guessing budgets.

They live in the "security" cache (the never-evicting, persisted Redis), not the LRU cache, so memory pressure or a
cache restart can't quietly reset a lockout. Increments are atomic (add + incr), so parallel misses all count.
"""

from django.core.cache import caches


def store():
    return caches["security"]


def count(key: str) -> int:
    return store().get(key, 0)


def bump(key: str, seconds: int) -> int:
    """Add one to `key` (window starts at the first hit) and return the new count."""
    c = store()
    c.add(key, 0, seconds)
    try:
        return c.incr(key)
    except ValueError:  # expired between add and incr
        c.set(key, 1, seconds)
        return 1


def clear(key: str) -> None:
    store().delete(key)
