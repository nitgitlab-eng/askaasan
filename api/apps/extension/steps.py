"""Multi-step browser tasks the Aasan Companion extension can observe live (M10 rca).

An author lists 1-8 steps for a browser_task activity; each step has a label, a `url_pattern` (an https:// glob: the host
may start with "*." for subdomains — but never over a public suffix like *.co.in or *.github.io —, `*` is the only
wildcard and only in the path; queries and fragments are never part of a pattern or of the evidence) and an optional
`text` the page must show. The extension asks the browser for host permission for exactly the steps' hosts, ticks steps as the learner
navigates, and — for text checks — only learns yes/no from the page (it never sends page content to Aasan).

Steps live in their own table (ObservedSteps), not in Activity.source: the Lab re-validates the whole source with a
strict schema on every edit, so an extra key there would break editing. Mirrors extension/steps.js — keep them in sync."""

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

MAX_STEPS = 8
MAX_LABEL, MAX_PATTERN, MAX_TEXT = 120, 300, 80
_HOST = re.compile(r"^(\*\.)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_PATTERN = re.compile(r"^https://([^/?#\\]+)(/[^?#\\]*)?$")
_BAD_URL_CHARS = re.compile(r"[\\\s\x00-\x1f\x7f]")
# Multi-label public suffixes (same file ships in extension/public_suffixes.json; a test keeps them identical).
PUBLIC_SUFFIXES = frozenset(
    json.loads((Path(__file__).with_name("public_suffixes.json")).read_text())["suffixes"]
)
MAX_EVIDENCE_TITLE = 120


class StepError(ValueError):
    def __init__(self, index: int, field: str, code: str):
        super().__init__(f"step {index + 1} {field}: {code}")
        self.index, self.field, self.code = index, field, code


def split_pattern(pattern: str) -> tuple[str, str] | None:
    """ "https://*.google.com/sheets/*" → ("*.google.com", "/sheets/*"); None if it isn't a valid step pattern."""
    m = _PATTERN.match(pattern or "")
    if not m:
        return None
    host, rest = m.group(1).lower(), m.group(2) or "/*"
    if not _HOST.match(host) or "*" in host[2:]:
        return None
    if host.startswith("*.") and is_public_suffix(host[2:]):
        return None  # "*.co.in" / "*.github.io" would mean permission for everybody's sites
    return host, rest


def is_public_suffix(domain: str) -> bool:
    domain = domain.lower().strip(".")
    return "." not in domain or domain in PUBLIC_SUFFIXES


def host_matches(host: str, pattern: str) -> bool:
    host, pattern = (host or "").lower().rstrip("."), (pattern or "").lower()
    if pattern.startswith("*."):
        return host == pattern[2:] or host.endswith(pattern[1:])
    return host == pattern


def _glob(path_pattern: str) -> re.Pattern:
    return re.compile("^" + ".*".join(re.escape(p) for p in path_pattern.split("*")) + "$", re.DOTALL)


def safe_url(url: str) -> bool:
    """No backslashes, whitespace or control characters: browsers read "https://evil.com\\x.google.com" as host
    evil.com while urlsplit reports "evil.com\\x.google.com" — refuse anything the two parsers could disagree on."""
    return bool(url) and not _BAD_URL_CHARS.search(url)


def strip_url(url: str) -> str:
    """scheme://host/path only (no query, fragment, credentials or port)."""
    u = urlsplit(url)
    return f"{u.scheme}://{(u.hostname or '').lower()}{u.path or '/'}"


def url_matches(url: str, pattern: str) -> bool:
    """Scheme must be https, the host must match the host part exactly (or as a subdomain for "*."), and the
    path must match the glob. Query and fragment are ignored. A "*" never reaches into the host."""
    parts = split_pattern(pattern)
    if not parts or not safe_url(url or ""):
        return False
    try:
        u = urlsplit(url or "")
        port = u.port
    except ValueError:
        return False
    if u.scheme != "https" or not u.hostname or u.username or u.password or port not in (None, 443):
        return False
    host_p, path_p = parts
    return host_matches(u.hostname, host_p) and bool(_glob(path_p).match(u.path or "/"))


def _clean(s) -> str:
    return " ".join(str(s or "").split())


def validate(raw) -> list[dict]:
    """Author input → normalised steps [{id, label, url_pattern, text}]. Raises StepError(index, field, code)."""
    if not isinstance(raw, list) or len(raw) > MAX_STEPS:
        raise StepError(0, "steps", "too_many" if isinstance(raw, list) else "not_a_list")
    out = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise StepError(i, "step", "not_an_object")
        label, pattern, text = (
            _clean(s.get("label")),
            str(s.get("url_pattern") or "").strip(),
            _clean(s.get("text")),
        )
        if not label or len(label) > MAX_LABEL:
            raise StepError(i, "label", "required" if not label else "too_long")
        if len(pattern) > MAX_PATTERN or not split_pattern(pattern):
            raise StepError(i, "url_pattern", "invalid")
        if len(text) > MAX_TEXT:
            raise StepError(i, "text", "too_long")
        out.append({"id": f"s{i + 1}", "label": label, "url_pattern": pattern, "text": text})
    return out


def hosts(steps: list[dict]) -> list[str]:
    seen = []
    for s in steps:
        parts = split_pattern(s["url_pattern"])
        if parts and parts[0] not in seen:
            seen.append(parts[0])
    return seen


def origins(steps: list[dict]) -> list[str]:
    """Chrome match patterns for chrome.permissions.request — exactly the steps' hosts, nothing broader."""
    return [f"https://{h}/*" for h in hosts(steps)]


def public(steps: list[dict], optional: bool = False) -> dict | None:
    return (
        {"steps": steps, "hosts": hosts(steps), "origins": origins(steps), "optional": bool(optional)}
        if steps
        else None
    )


class EvidenceError(ValueError):
    def __init__(self, code: str, step: str = ""):
        super().__init__(code)
        self.code, self.step = code, step


def check_evidence(steps: list[dict], observed) -> list[dict]:
    """The extension's observed-step list must cover every step, in order, each with a URL that matches that step's
    pattern (re-checked here) and, for text steps, a positive text check. Returns the cleaned evidence to store."""
    if not isinstance(observed, list) or not steps:
        raise EvidenceError("steps_mismatch")
    if len(observed) != len(steps):
        raise EvidenceError("steps_incomplete")
    out = []
    for step, ob in zip(steps, observed):
        if not isinstance(ob, dict) or ob.get("step") != step["id"]:
            raise EvidenceError("steps_mismatch", step["id"])
        url = str(ob.get("url") or "")[:2048]
        if not url_matches(url, step["url_pattern"]):
            raise EvidenceError("step_url_mismatch", step["id"])
        if step["text"] and ob.get("text_found") is not True:
            raise EvidenceError("step_text_missing", step["id"])
        out.append(
            {
                "step": step["id"],
                "url": strip_url(url)[:500],
                "title": _clean(ob.get("title"))[:MAX_EVIDENCE_TITLE],
                "text_found": True if step["text"] else None,
            }
        )
    return out
