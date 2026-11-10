"""Certificate templates: validation, resolution (most specific wins) and the sample certificate used for previews."""

import re
from dataclasses import dataclass, field

from django.utils import timezone

from .models import Certificate, CertificateTemplate

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
MEDIA = re.compile(r"^/api/media/[0-9a-f]{32}\.(webp|png|jpg)$")
KINDS = {k for k, _ in Certificate.Kind.choices}
LANGS = {"en", "ta", "hi", "te", "kn", "ml", "bn", "mr", "gu"}
DEFAULT_COLORS = {"ink": "#1f2a44", "accent": "#c2410c", "gold": "#b8860b", "paper": "#fffaf2"}
TEXT_FIELDS = {
    "headline": 80,
    "verb": 120,
    "signatory_name": 80,
    "signatory_title": 80,
    "footer_note": 160,
}


@dataclass
class Look:
    """Everything the renderer needs, with defaults filled in."""

    layout: str = "classic"
    colors: dict = field(default_factory=lambda: dict(DEFAULT_COLORS))
    headline: str = ""
    verb: str = ""
    logo: str = ""
    signature: str = ""
    signatory_name: str = ""
    signatory_title: str = ""
    footer_note: str = ""


def look_of(t: CertificateTemplate | None) -> Look:
    if not t:
        return Look()
    return Look(
        layout=t.layout,
        colors={**DEFAULT_COLORS, **{k: v for k, v in (t.colors or {}).items() if k in DEFAULT_COLORS}},
        headline=t.headline,
        verb=t.verb,
        logo=t.logo,
        signature=t.signature,
        signatory_name=t.signatory_name,
        signatory_title=t.signatory_title,
        footer_note=t.footer_note,
    )


def _lang(cert) -> str:
    prof = getattr(getattr(cert, "user", None), "profile", None)
    lang = getattr(prof, "language", "") or ""
    return lang if lang in LANGS else "en"


def resolve(cert) -> CertificateTemplate | None:
    """org+kind+lang → org+kind → org+lang → org → platform (same order) → None (built-in look)."""
    if not isinstance(cert, Certificate):  # stand-ins (tests, tools) get the built-in look
        return None
    lang = _lang(cert)
    order = [(cert.kind, lang), (cert.kind, ""), ("", lang), ("", "")]
    rows = list(
        CertificateTemplate.objects.filter(
            active=True, kind__in=[cert.kind, ""], language__in=[lang, ""]
        ).filter(org_id__in=[cert.org_id] if cert.org_id else [])
    ) + list(
        CertificateTemplate.objects.filter(
            active=True, org__isnull=True, kind__in=[cert.kind, ""], language__in=[lang, ""]
        )
    )
    for scope in ([cert.org_id] if cert.org_id else []) + [None]:
        for kind, language in order:
            for t in rows:
                if t.org_id == scope and t.kind == kind and t.language == language:
                    return t
    return None


def clean(data: dict) -> tuple[dict, str | None]:
    """Validated template fields from a request body → (fields, error code)."""
    out = {}
    if "kind" in data:
        if data["kind"] not in KINDS | {""}:
            return {}, "bad_kind"
        out["kind"] = data["kind"]
    if "language" in data:
        if data["language"] not in LANGS | {""}:
            return {}, "bad_language"
        out["language"] = data["language"]
    if "layout" in data:
        if data["layout"] not in CertificateTemplate.Layout.values:
            return {}, "bad_layout"
        out["layout"] = data["layout"]
    if "colors" in data:
        c = data["colors"]
        if not isinstance(c, dict) or not all(
            k in DEFAULT_COLORS and isinstance(v, str) and HEX.match(v) for k, v in c.items()
        ):
            return {}, "bad_colors"
        out["colors"] = c
    for k in ("logo", "signature"):
        if k in data:
            v = str(data[k] or "")
            if v and not MEDIA.match(v):
                return {}, f"bad_{k}"  # our own uploaded images only: never an external URL in a PDF
            out[k] = v
    for k, n in TEXT_FIELDS.items():
        if k in data:
            out[k] = " ".join(str(data[k] or "").split())[:n]
    if "active" in data:
        if not isinstance(data["active"], bool):
            return {}, "bad_active"
        out["active"] = data["active"]
    return out, None


def template_out(t: CertificateTemplate) -> dict:
    return {
        "id": t.id,
        "org_id": t.org_id,
        "kind": t.kind,
        "language": t.language,
        "layout": t.layout,
        "colors": {**DEFAULT_COLORS, **(t.colors or {})},
        "headline": t.headline,
        "verb": t.verb,
        "logo": t.logo,
        "signature": t.signature,
        "signatory_name": t.signatory_name,
        "signatory_title": t.signatory_title,
        "footer_note": t.footer_note,
        "active": t.active,
        "updated_at": t.updated_at,
    }


def sample(kind: str, issuer_name: str = "Aasan", org=None) -> Certificate:
    """An unsaved certificate for previews (never stored)."""
    return Certificate(
        kind=kind if kind in KINDS else "course",
        title="AI for small businesses",
        learner_name="Priya Ramesh",
        issuer_name=issuer_name,
        issuer_type="organisation" if org else "aasan",
        org=org,
        author_name="",
        detail={"pct": 92, "minutes": 95},
        code="PREVIEW-0000-0000",
        issued_at=timezone.now(),
    )
