"""R6/R7: PDFs (certificates, invoices, pilot report) draw Tamil and other non-Latin-1 text with the Noto fonts from the
font directory, and fall back to '?' (never a crash, never markup injection) when the fonts are not installed."""

import io
import os
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.credentials import pdf_fonts

TAMIL = "தமிழ்செல்வி"


@pytest.fixture
def font_dir(settings, tmp_path):
    """Point PDF_FONT_DIR somewhere and reset the registered-font cache before and after."""

    def use(path):
        settings.PDF_FONT_DIR = str(path)
        pdf_fonts.fonts.cache_clear()
        return path

    yield use
    pdf_fonts.fonts.cache_clear()


def _real_fonts() -> Path | None:
    d = Path(os.environ.get("PDF_TEST_FONT_DIR") or pdf_fonts.font_dir())
    return (
        d if (d / "NotoSans-Regular.ttf").is_file() and (d / "NotoSansTamil-Regular.ttf").is_file() else None
    )


def _cert(**kw):
    return SimpleNamespace(
        code="AB12-CD34",
        issuer_name="Aasan",
        issuer_type="aasan",
        kind="course",
        learner_name=TAMIL,
        title="Excel அடிப்படை",
        author_name="கமலா",
        detail={},
        issued_at=timezone.now(),
        **kw,
    )


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader

    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def _has_tamil(pdf: bytes) -> bool:
    """Unshaped, the extracted text is the name itself. With HarfBuzz shaping, reordered vowel signs and conjuncts are
    stored as glyphs with no one-to-one Unicode mapping, so check the Tamil font is embedded and the name's unshaped
    opening letters survive instead."""
    text = _text(pdf).replace(" ", "")
    if pdf_fonts.fonts()["shaping"]:
        return b"NotoSansTamil" in pdf and TAMIL[:3] in text and "?????" not in text
    return TAMIL in text


def test_without_fonts_falls_back_to_question_marks(font_dir, tmp_path):
    from apps.billing.invoices import _safe
    from apps.credentials.pdf import render, safe

    font_dir(tmp_path)
    assert pdf_fonts.fonts() is None
    assert safe("தமிழ் name") == "????? name"
    assert safe('<img src="x">') == '&lt;img src="x"&gt;'
    assert _safe("a\n<b>") == "a<br/>&lt;b&gt;"
    assert render(_cert())[:5] == b"%PDF-"


def test_with_fonts_tamil_is_drawn_not_replaced(font_dir):
    d = _real_fonts()
    if not d:
        pytest.skip("add NotoSans-Regular.ttf and NotoSansTamil-Regular.ttf to api/assets/fonts to run")
    from apps.credentials.pdf import render, safe

    font_dir(d)
    m = safe(f"<i>{TAMIL}</i> & co")
    assert "?" not in m and "<i>" not in m and "&lt;i&gt;" in m
    assert '<font name="AasanNotoSansTamil">' in m or '<font name="AasanNotoSans">' in m
    pdf = render(_cert())
    assert pdf[:5] == b"%PDF-" and b"/FontFile2" in pdf  # an embedded TrueType subset
    assert _has_tamil(pdf)


def test_invoice_and_pilot_pdf_keep_tamil_with_fonts(font_dir):
    d = _real_fonts()
    if not d:
        pytest.skip("add NotoSans-Regular.ttf and NotoSansTamil-Regular.ttf to api/assets/fonts to run")
    from apps.billing.invoices import render_pdf as invoice_pdf
    from apps.orgs.teach_report import render_pdf as pilot_pdf

    font_dir(d)
    inv = SimpleNamespace(
        number="AASA/2026-27/00001",
        issued_at=timezone.now(),
        taxable_paise=8475,
        igst_paise=1525,
        cgst_paise=0,
        sgst_paise=0,
        total_paise=10000,
        seller={"name": "Aasan", "address": "Chennai", "state": "Tamil Nadu", "gstin": ""},
        buyer={"name": TAMIL, "email": "x@example.com", "state": "Kerala", "gstin": ""},
        lines=[
            {
                "description": "Pro",
                "sac": "999293",
                "qty": 1,
                "list_paise": 10000,
                "discount_paise": 0,
                "total_paise": 10000,
            }
        ],
        order=SimpleNamespace(rp_order_id="o", rp_payment_id="p", mode="test"),
    )
    assert _has_tamil(invoice_pdf(inv))
    k = {"n": 1, "of": 2, "value": 0.5}
    rep = {
        "org": TAMIL,
        "from": date(2026, 1, 1),
        "to": date(2026, 3, 1),
        "weekly": [],
        "courses": [],
        "definitions": {},
        "kpis": {
            "learners": 2,
            "activation": k,
            "sustained": k,
            "completion": k,
            "gain": {"pairs": 0, "avg_pre": None, "avg_post": None, "avg_gain": None},
            "recommend": {"source": None, "value": None, "nps": None, "ratings": 0, "promoters": None},
        },
    }
    assert _has_tamil(pilot_pdf(rep))
