"""Lenient parsing of raw request values: a malformed number is a 400 or "none found", never a 500."""

from rest_framework.exceptions import ValidationError


def to_int(v) -> int | None:
    """An id or number sent by the client, or None when missing or malformed."""
    if isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def int_list(v, cap: int) -> list[int]:
    """A list of ids (at most `cap`); anything that isn't a list of integers is refused with 400 bad_ids."""
    if v in (None, ""):
        return []
    if not isinstance(v, list | tuple):
        raise ValidationError({"code": "bad_ids"})
    out = [to_int(x) for x in v[:cap]]
    if None in out:
        raise ValidationError({"code": "bad_ids"})
    return out


def flag(v) -> bool:
    """A settings toggle: JSON true/false, or form strings like "false"/"0"/"off" (bool("false") would be True)."""
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)
