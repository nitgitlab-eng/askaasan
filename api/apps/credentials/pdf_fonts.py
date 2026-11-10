"""Unicode text for reportlab PDFs (certificates, invoices, pilot report).

reportlab's built-in Helvetica/Times only cover Latin-1, so Tamil and other Indian-language names used to print as '?'.
If TTF fonts are present in the font directory (settings.PDF_FONT_DIR, else api/assets/fonts), they are registered once:
NotoSans-Regular.ttf (+ optional NotoSans-Bold.ttf) as the base, and every other NotoSans*-Regular.ttf there (e.g.
NotoSansTamil-Regular.ttf, NotoSansDevanagari-Regular.ttf, each with an optional -Bold sibling) as script fallbacks.
markup() then wraps each run of non-Latin-1 text in a <font> tag naming a font that has the glyphs. Without fonts it
behaves exactly as before: non-Latin-1 characters become '?'. Proper Indic shaping (vowel signs placed before the
consonant, conjuncts) also needs the optional uharfbuzz package; apply() switches it on when it is importable."""

import functools
import logging
from pathlib import Path
from xml.sax.saxutils import escape

from django.conf import settings

log = logging.getLogger(__name__)
BASE = "NotoSans"


def font_dir() -> Path:
    return Path(getattr(settings, "PDF_FONT_DIR", "") or Path(settings.BASE_DIR) / "assets" / "fonts")


def _register(name: str, regular: Path):
    """Register `name` (+ `name`-Bold when the Bold file exists) as a family so <b> works. Returns (name, bold, cmap)."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    reg = TTFont(name, str(regular))
    pdfmetrics.registerFont(reg)
    bold_path = regular.with_name(regular.name.replace("-Regular", "-Bold"))
    bold = name
    if bold_path.is_file():
        bold = f"{name}-Bold"
        pdfmetrics.registerFont(TTFont(bold, str(bold_path)))
    for b, i, face in ((0, 0, name), (0, 1, name), (1, 0, bold), (1, 1, bold)):
        addMapping(name, b, i, face)
        addMapping(bold, b, i, bold if b else name)
    return name, bold, frozenset(reg.face.charToGlyph)


@functools.cache
def fonts() -> dict | None:
    """{'base': (name, bold, cmap), 'fallbacks': [...], 'shaping': bool}, or None when no base font is installed."""
    d = font_dir()
    base = d / f"{BASE}-Regular.ttf"
    if not base.is_file():
        return None
    try:
        out = {"base": _register("Aasan" + BASE, base), "fallbacks": []}
        for p in sorted(d.glob(f"{BASE}?*-Regular.ttf")):
            out["fallbacks"].append(_register("Aasan" + p.name.removesuffix("-Regular.ttf"), p))
    except Exception:  # a corrupt or unsupported font file must not break PDF downloads
        log.exception("pdf fonts: could not register fonts from %s; using built-in fonts", d)
        return None
    try:
        import uharfbuzz  # noqa: F401

        out["shaping"] = True
    except ImportError:
        out["shaping"] = False
    return out


def _font_for(ch: str, f: dict) -> str | None:
    cp = ord(ch)
    for name, _, cmap in (f["base"], *f["fallbacks"]):
        if cp in cmap:
            return name
    return None


def _keeps(ch: str, font: str | None, f: dict | None) -> bool:
    """A space, digit or punctuation mark right after a script-fallback run stays in that run when the fallback font has
    it: switching fonts mid-phrase makes reportlab's HarfBuzz shaping drop characters ("தவறு: பட்டியல்" printed
    as "தவறுபட்டியல்")."""
    if not (font and f) or ch.isalpha():
        return False
    return any(name == font and ord(ch) in cmap for name, _, cmap in f["fallbacks"])


def markup(s, *, control: str = "", newlines: bool = False) -> str:
    """`s` as reportlab Paragraph markup: XML-escaped (so a name like `<img src=...>` prints as text) and every character
    either drawable or replaced by '?'. `control` replaces characters below 32 (None keeps them); `newlines` turns
    newlines into <br/>."""
    f = fonts()
    out, run, run_font = [], [], None

    def flush():
        if run:
            text = escape("".join(run))
            out.append(f'<font name="{run_font}">{text}</font>' if run_font else text)
            run.clear()

    for ch in str(s or ""):
        if ch == "\n" and newlines:
            flush()
            run_font = None
            out.append("<br/>")
            continue
        if ord(ch) < 32 and control is not None:
            ch = control
        font = None
        if ord(ch) >= 256:
            font = _font_for(ch, f) if f else None
            if font is None:
                ch = "?"
        elif _keeps(ch, run_font, f):
            font = run_font
        if font != run_font:
            flush()
            run_font = font
        run.append(ch)
    flush()
    return "".join(out)


def plain(s) -> str:
    """For non-markup strings (PDF metadata such as author/title): Unicode is fine there, only strip control chars."""
    return "".join(ch for ch in str(s or "") if ord(ch) >= 32)


def apply(style):
    """Turn on HarfBuzz shaping for a ParagraphStyle when fonts and uharfbuzz are both available (shaping needs the
    style's own font to be a TTF, so the base font replaces the built-in one, keeping bold)."""
    f = fonts()
    if f and f["shaping"] and hasattr(style, "fontName"):  # ListStyle etc. have no font of their own
        name, bold, _ = f["base"]
        style.fontName = bold if "Bold" in style.fontName else name
        style.shaping = 1
    return style
