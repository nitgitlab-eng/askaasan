"""Checks that don't rely on the model: run on every learner turn and every streamed reply.

- `screen(text)` masks secrets (OTP/PIN/CVV, passwords, Aadhaar, PAN, card, UPI id, phone) before the text reaches the
  model, a web search or the database, and flags words that may mean the learner is in danger (en / ta / Tanglish)
  or an attempt to override the rules. Crisis adds a one-turn note to the prompt; injection is only logged.
- `OutputFilter` removes markdown images and turns links the model wrote into plain text while the reply streams
  (sources the app lists come from the server, never from the model's text).
Logged with kinds and counts only, never the text."""

import re
from dataclasses import dataclass, field

# ── Secrets ────────────────────────────────────────────────────────────────────────────────────────────────────────

_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def _verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(d)]]
    return c == 0


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


_SECRET_WORD = re.compile(
    r"(?i)\b(otp|one[- ]time[- ]password|pin(?!\s*code)|m-?pin|upi pin|cvv|cvc)\b(\s*(?:no\.?|number|code))?"
    r"(\s*(?:is|was|:|=|-)?\s*)(\d{3,8})\b"
)
_PASSWORD = re.compile(
    r"(?i)\b(password|passcode|passwd|pwd|கடவுச்சொல்)(\s*(?:is|was|:|=|-)\s*|\s+)([^\s,;]{3,64})"
)
# "password is the …", "password manager": not a password
_PASSWORD_STOP = {"the", "a", "an", "my", "your", "for", "to", "of", "and", "or", "is", "was", "reset", "manager"}  # fmt: skip
_AADHAAR = re.compile(r"(?<![\d.])([2-9]\d{3})[ -]?(\d{4})[ -]?(\d{4})(?![\d.])")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_CARD = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")
_UPI = re.compile(r"(?<![\w.@-])[\w.-]{2,64}@[A-Za-z]{2,20}\b(?!\.[A-Za-z])")
_PHONE = re.compile(r"(?<![\d.])(?:\+91[ -]?|0)?([6-9]\d{4}[ -]?\d{5})(?![\d.])")


def mask_secrets(text: str) -> tuple[str, list[str]]:
    """→ (text with secrets replaced by "[hidden …]", kinds found)."""
    kinds: list[str] = []

    def hide(kind: str, label: str):
        def sub(m):
            kinds.append(kind)
            return label

        return sub

    def secret_word(m):
        kinds.append("otp")
        return f"{m.group(1)}{m.group(2) or ''}{m.group(3)}[hidden code]"

    text = _SECRET_WORD.sub(secret_word, text)

    def password(m):
        if m.group(3).lower() in _PASSWORD_STOP:
            return m.group(0)
        kinds.append("password")
        return f"{m.group(1)}{m.group(2)}[hidden password]"

    text = _PASSWORD.sub(password, text)

    def card(m):
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits) and len(set(digits)) > 2:
            kinds.append("card")
            return "[hidden card number]"
        return m.group(0)

    text = _CARD.sub(card, text)

    def aadhaar(m):
        digits = "".join(m.groups())
        if _verhoeff_ok(digits):
            kinds.append("aadhaar")
            return "[hidden Aadhaar number]"
        return m.group(0)

    text = _AADHAAR.sub(aadhaar, text)
    text = _PAN.sub(hide("pan", "[hidden PAN]"), text)
    text = _UPI.sub(hide("upi", "[hidden UPI id]"), text)
    text = _PHONE.sub(hide("phone", "[hidden phone number]"), text)
    return text, kinds


# ── Danger and override attempts ───────────────────────────────────────────────────────────────────────────────────

_CRISIS = re.compile(
    r"(?i)("
    r"\bkill(ing)? my ?self\b|\bend(ing)? my (own )?life\b|\btake my (own )?life\b|\bwant(ed)? to die\b|"
    r"\bwanna die\b|\bsuicid(e|al)\b|\bself[- ]?harm|\bcut(ting)? my ?self\b|\bhurt(ing)? my ?self\b|"
    r"\bno (reason|point) (to|in) liv|\bbetter off dead\b|\bdon'?t want to (live|be alive)\b|"
    r"\b(he|she|they|someone|my \w+) (touches|touched|hits|hit|beats|beat) me\b|\bbeing abused\b|\babusing me\b|"
    r"தற்கொலை|சாக (வேண்டும்|போகிறேன்|விரும்புகிறேன்)|சாகணும்|சாகப் போறேன்|உயிரை மாய்த்|வாழ (விருப்பம் இல்லை|பிடிக்கவில்லை)|"
    r"\b(saaga?nu?m|saaga poren|sethudu?ven|sethuduren|tha?r?kolai|thatkolai|vaazha pidikkala|"
    r"vazha pidikala)\b"
    r")"
)
_INJECTION = re.compile(
    r"(?i)(ignore (all |any )?(the |your )?(previous|above|prior|earlier) (instructions|rules|prompts?)|"
    r"\b(system|developer) prompt\b|\bdeveloper mode\b|\bjailbreak|\bDAN mode\b|"
    r"(reveal|show|print|repeat) (me )?(your|the) (instructions|rules|prompt)|"
    r"pretend (you have|there are) no (rules|restrictions)|\bdisregard (your|the) (rules|guidelines))"
)


@dataclass
class Screened:
    text: str
    masked: list[str] = field(default_factory=list)
    crisis: bool = False
    injection: bool = False

    @property
    def flags(self) -> list[str]:
        return [
            *self.masked,
            *(["crisis"] if self.crisis else []),
            *(["injection"] if self.injection else []),
        ]


def screen(text: str) -> Screened:
    masked_text, kinds = mask_secrets(text or "")
    return Screened(
        text=masked_text,
        masked=sorted(set(kinds)),
        crisis=bool(_CRISIS.search(text or "")),
        injection=bool(_INJECTION.search(text or "")),
    )


def log_flags(s: Screened, user_id: int | None, surface: str) -> None:
    """Kinds only, never the words."""
    if not s.flags:
        return
    from apps.accounts.security_log import security_event

    security_event("ai_guard", user_id=user_id, surface=surface, flags=",".join(s.flags))


def screen_turn(text: str, user_id: int | None, surface: str) -> Screened:
    s = screen(text)
    log_flags(s, user_id, surface)
    return s


# ── Output ─────────────────────────────────────────────────────────────────────────────────────────────────────────

_IMAGE = re.compile(r"!\[[^\]\n]{0,300}\]\([^)\n]{0,2000}\)")
_LINK = re.compile(r"(?<!!)\[([^\]\n]{1,300})\]\(([^)\s\n]{1,2000})(?:\s+\"[^\"\n]*\")?\)")
_HTML_IMG = re.compile(r"(?i)<img\b[^>]*>")
# A reply chunk may end in the middle of one of these; hold that tail back until it is complete.
_OPEN_TAIL = re.compile(r"(!?\[[^\]\n]{0,300}(\](\([^)\n]{0,2000})?)?|!|<(i(m(g\b[^>\n]{0,300})?)?)?)$")


def clean_output(text: str, allowed_urls=()) -> str:
    allowed = set(allowed_urls)
    text = _IMAGE.sub("", text)
    text = _HTML_IMG.sub("", text)
    return _LINK.sub(lambda m: m.group(0) if m.group(2) in allowed else m.group(1), text)


class OutputFilter:
    """Streams a reply through clean_output, holding back only an unfinished image/link at the end of a chunk."""

    def __init__(self, allowed_urls=()):
        self.allowed = tuple(allowed_urls)
        self.pending = ""

    def feed(self, delta: str) -> str:
        text = self.pending + delta
        m = _OPEN_TAIL.search(text)
        if m and len(text) - m.start() < 2400:
            self.pending, text = text[m.start() :], text[: m.start()]
        else:
            self.pending = ""
        return clean_output(text, self.allowed)

    def flush(self) -> str:
        text, self.pending = self.pending, ""
        return clean_output(text, self.allowed)
