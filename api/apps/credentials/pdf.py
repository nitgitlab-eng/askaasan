"""Certificate PDF: A4 landscape, drawn with reportlab. Every dynamic value is escaped before it reaches Paragraph markup
(a course title like `<img src=...>` must print as text, never become markup reportlab would act on)."""

import io

from django.utils import timezone

from . import pdf_fonts
from .services import verify_url
from .templates import Look, look_of, resolve

MUTED = "#55607a"

HEADLINES = {
    "course": ("CERTIFICATE OF COMPLETION", "has successfully completed the course"),
    "scenario": ("CERTIFICATE OF PRACTICE", "has successfully completed the role-play practice"),
    "test": ("CERTIFICATE OF ACHIEVEMENT", "has passed the knowledge test"),
    "workshop": ("CERTIFICATE OF COMPLETION — WORKSHOP", "has successfully completed the AI-led workshop"),
}


def safe(s) -> str:
    """XML-escaped for Paragraph markup. Tamil and other non-Latin-1 text is drawn with the installed Noto fonts
    (pdf_fonts); without them it falls back to '?' because built-in Helvetica/Times have no Indic glyphs."""
    return pdf_fonts.markup(s, control=" ")


def issuer_line(cert) -> str:
    return "Issued by (an organisation on Aasan)" if cert.issuer_type == "organisation" else "Issued by"


def _image(c, url: str, x, y, max_w, max_h, *, centre=True) -> bool:
    """Draw one of our own uploaded images (logo/signature), scaled to fit. A missing/broken file draws nothing."""
    from django.core.files.storage import default_storage
    from reportlab.lib.utils import ImageReader

    name = url.rsplit("/", 1)[-1]
    try:
        with default_storage.open(f"aasan/{name}", "rb") as fh:
            img = ImageReader(io.BytesIO(fh.read()))
        iw, ih = img.getSize()
        scale = min(max_w / iw, max_h / ih)
        dw, dh = iw * scale, ih * scale
        c.drawImage(img, x - dw / 2 if centre else x, y, dw, dh, mask="auto")
        return True
    except Exception:  # noqa: BLE001
        return False


def render(cert, look: Look | None = None) -> bytes:
    """`look`: for previews; normally the certificate's template is resolved here."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Paragraph

    # rl_config.trustedHosts/trustedSchemes are locked down once in CredentialsConfig.ready().
    look = look or look_of(resolve(cert))
    INK, ACCENT, GOLD, PAPER = (look.colors[k] for k in ("ink", "accent", "gold", "paper"))
    w, h = landscape(A4)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(w, h))
    c.setTitle(f"Certificate {cert.code}")
    c.setAuthor(pdf_fonts.plain(cert.issuer_name))

    c.setFillColor(colors.HexColor(PAPER))
    c.rect(0, 0, w, h, stroke=0, fill=1)
    if look.layout == "modern":  # a solid accent band on the left, thin gold rule
        c.setFillColor(colors.HexColor(ACCENT))
        c.rect(0, 0, 22 * mm, h, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(GOLD))
        c.rect(22 * mm, 0, 1.2 * mm, h, stroke=0, fill=1)
    elif look.layout == "minimal":  # no frame: one hairline top and bottom
        c.setStrokeColor(colors.HexColor(GOLD))
        c.setLineWidth(0.6)
        c.line(30 * mm, h - 22 * mm, w - 30 * mm, h - 22 * mm)
        c.line(30 * mm, 18 * mm, w - 30 * mm, 18 * mm)
    else:  # classic: paper, double frame and corner ornaments
        c.setStrokeColor(colors.HexColor(INK))
        c.setLineWidth(3)
        c.rect(12 * mm, 12 * mm, w - 24 * mm, h - 24 * mm)
        c.setStrokeColor(colors.HexColor(GOLD))
        c.setLineWidth(1)
        c.rect(16 * mm, 16 * mm, w - 32 * mm, h - 32 * mm)
        c.setFillColor(colors.HexColor(ACCENT))
        for x, y in ((16, 16), (w / mm - 16, 16), (16, h / mm - 16), (w / mm - 16, h / mm - 16)):
            c.circle(x * mm, y * mm, 2.2 * mm, stroke=0, fill=1)
        c.setFillColor(colors.HexColor(ACCENT))
        c.rect(w / 2 - 30 * mm, h - 34 * mm, 60 * mm, 1.2 * mm, stroke=0, fill=1)
    if look.logo:
        _image(c, look.logo, w / 2, h - 32 * mm, 50 * mm, 14 * mm)

    def centred(markup, y, size, font="Helvetica", color=INK, leading=None, width=w - 70 * mm):
        st = pdf_fonts.apply(
            ParagraphStyle(
                "x",
                fontName=font,
                fontSize=size,
                leading=leading or size * 1.25,
                alignment=TA_CENTER,
                textColor=colors.HexColor(color),
            )
        )
        p = Paragraph(markup, st)
        _, ph = p.wrap(width, h)
        p.drawOn(c, (w - width) / 2, y - ph)
        return y - ph

    head, verb = HEADLINES.get(cert.kind, HEADLINES["course"])
    head, verb = safe(look.headline) if look.headline else head, safe(look.verb) if look.verb else verb
    y = h - (46 if look.logo else 40) * mm
    top = safe(str(cert.issuer_name).upper()) + (
        " · AN ORGANISATION ON AASAN" if cert.issuer_type == "organisation" else ""
    )
    y = centred(top, y, 13, "Helvetica-Bold", ACCENT) - 4 * mm
    y = centred(head, y, 26, "Times-Bold") - 8 * mm
    y = centred("This is to certify that", y, 13, "Helvetica", MUTED) - 5 * mm
    y = centred(safe(cert.learner_name), y, 30, "Times-BoldItalic") - 5 * mm
    c.setStrokeColor(colors.HexColor(GOLD))
    c.line(w / 2 - 70 * mm, y + 2 * mm, w / 2 + 70 * mm, y + 2 * mm)
    y = centred(verb, y - 3 * mm, 13, "Helvetica", MUTED) - 4 * mm
    y = centred(safe(cert.title), y, 20, "Helvetica-Bold", INK, width=w - 90 * mm)
    if cert.author_name:
        y = centred(f"Course by {safe(cert.author_name)}", y - 3 * mm, 11, "Helvetica-Oblique", MUTED)
    if cert.kind == "test" and (pct := (cert.detail or {}).get("pct")) is not None:
        centred(f"Score: {int(pct)}%", y - 4 * mm, 12, "Helvetica", MUTED)
    if cert.kind == "workshop":
        d = cert.detail or {}
        bits = [f"Duration: {int(d['minutes'])} minutes" if d.get("minutes") else ""]
        bits.append(f"Score: {int(d['pct'])}%" if d.get("pct") is not None else "")
        if line := " · ".join(b for b in bits if b):
            centred(line, y - 4 * mm, 12, "Helvetica", MUTED)

    # Footer: date · issuer · verification
    issued = timezone.localtime(cert.issued_at).strftime("%d %B %Y")
    small = pdf_fonts.apply(
        ParagraphStyle(
            "s",
            fontName="Helvetica",
            fontSize=9.5,
            leading=12,
            alignment=TA_CENTER,
            textColor=colors.HexColor(MUTED),
        )
    )
    issuer = issuer_line(cert)
    middle = (
        f"<b>{safe(look.signatory_name)}</b><br/>{safe(look.signatory_title) or safe(cert.issuer_name)}"
        if look.signatory_name
        else f"<b>{safe(cert.issuer_name)}</b><br/>{issuer}"
    )
    if look.signature:
        _image(c, look.signature, w / 2, 47.5 * mm, 40 * mm, 13 * mm)
    cols = [
        (f"<b>{issued}</b><br/>Date of issue", w / 2 - 95 * mm),
        (middle, w / 2 - 30 * mm),
        (f"<b>{safe(cert.code)}</b><br/>Certificate ID", w / 2 + 35 * mm),
    ]
    for markup, x in cols:
        p = Paragraph(markup, small)
        p.wrap(60 * mm, 30 * mm)
        p.drawOn(c, x, 32 * mm)
    for x in (w / 2 - 95 * mm, w / 2 - 30 * mm, w / 2 + 35 * mm):
        c.setStrokeColor(colors.HexColor("#c9c2b5"))
        c.line(x + 8 * mm, 46 * mm, x + 52 * mm, 46 * mm)
    note = f"{safe(look.footer_note)} · " if look.footer_note else ""
    p = Paragraph(f"{note}Verify this certificate at {safe(verify_url(cert))}", small)
    p.wrap(w - 60 * mm, 20 * mm)
    p.drawOn(c, 30 * mm, 21 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()
