"""One spreadsheet formula-injection guard for every CSV export (orgs, guests, journeys, billing)."""

_FORMULA = ("=", "+", "-", "@", "|")
_CONTROL = ("\t", "\r", "\n")


def csv_safe(v):
    """Prefix an apostrophe to text a spreadsheet would run as a formula: =, +, -, @, | at the start, even after
    leading spaces (Excel trims them), or a leading tab / CR / newline. Non-strings pass through unchanged."""
    if isinstance(v, str) and (v[:1] in _CONTROL or v.lstrip()[:1] in _FORMULA):
        return "'" + v
    return v
