"""GST tax invoices. Prices are GST-inclusive (18% on training/coaching services): taxable value = total / 1.18.
Same state as the seller → CGST 9% + SGST 9%; otherwise IGST 18%. Numbered per Indian financial year (Apr–Mar)."""

import io
import re

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

GST_RATE = 18
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
STATES = [
    "Andaman and Nicobar Islands",
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chandigarh",
    "Chhattisgarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jammu and Kashmir",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Ladakh",
    "Lakshadweep",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Puducherry",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
]


def financial_year(d) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def split_gst(total_paise: int, intra_state: bool) -> dict:
    taxable = round(total_paise * 100 / (100 + GST_RATE))
    tax = total_paise - taxable
    if intra_state:
        cgst = tax // 2
        return {"taxable_paise": taxable, "cgst_paise": cgst, "sgst_paise": tax - cgst, "igst_paise": 0}
    return {"taxable_paise": taxable, "cgst_paise": 0, "sgst_paise": 0, "igst_paise": tax}


def _ascii_name(s: str) -> str:
    return s if s and s.isascii() else ""


@transaction.atomic
def issue_invoice(order):
    from apps.legal.models import SiteInfo

    from .models import Invoice

    if Invoice.objects.filter(order=order).exists():
        return Invoice.objects.get(order=order)
    site = SiteInfo.objects.filter(pk=1).first() or SiteInfo()
    seller_state = site.state or "Tamil Nadu"
    buyer_state = order.buyer_state or seller_state  # B2C with no address: place of supply = supplier's state
    fy = financial_year(timezone.localdate(order.paid_at or timezone.now()))
    seq = (Invoice.objects.select_for_update().filter(fy=fy).aggregate(m=Max("seq"))["m"] or 0) + 1
    prefix = re.sub(r"[^A-Z]", "", (site.brand or "Aasan").upper())[:4] or "INV"
    user = order.user
    buyer_name = (
        order.buyer_name
        or (order.org.name if order.org_id else "")
        or _ascii_name(getattr(getattr(user, "profile", None), "display_name", ""))
        or (user.email if user else "")
    )
    what = (
        order.label  # "Workshop: <title>, <date>"
        if order.workshop_run_id or not order.plan_id
        else f"{order.plan.name} — {order.seats} seat{'' if order.seats == 1 else 's'} for {order.org.name}"
        if order.org_id
        else f"Gift: {order.plan.name} ({order.plan.period_days} days)"
        if order.is_gift
        else f"{order.plan.name} ({order.plan.period_days} days)"
    )
    lines = [
        {
            "description": what,
            "sac": site.hsn_sac,
            "qty": order.seats,
            "list_paise": order.list_paise or order.amount_paise,
            "discount_paise": order.discount_paise,
            "total_paise": order.amount_paise,
        }
    ]
    return Invoice.objects.create(
        order=order,
        fy=fy,
        seq=seq,
        number=f"{prefix}/{fy}/{seq:05d}",
        seller={
            "name": site.legal_name or site.brand,
            "address": site.address,
            "gstin": site.gstin,
            "state": seller_state,
            "email": site.support_email,
        },
        buyer={
            "name": buyer_name[:160],
            "email": user.email if user else "",
            "gstin": order.buyer_gstin,
            "state": buyer_state,
        },
        total_paise=order.amount_paise,
        lines=lines,
        **split_gst(order.amount_paise, buyer_state == seller_state),
    )


def _rs(paise: int) -> str:
    return f"Rs. {paise / 100:,.2f}"  # built-in PDF fonts have no ₹ glyph


def _safe(s) -> str:
    """A value for reportlab Paragraph markup: XML-escaped, so names can't inject tags such as <img src=...> (which
    reportlab would fetch) or break the layout. Tamil and other scripts use the installed Noto fonts, else '?'."""
    from apps.credentials.pdf_fonts import markup

    return markup(s, control=None, newlines=True)


def render_pdf(inv) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from apps.credentials.pdf_fonts import apply

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=f"Tax invoice {inv.number}",
    )
    ss = getSampleStyleSheet()
    for st in ss.byName.values():
        apply(st)
    s, b = inv.seller, inv.buyer
    order = inv.order
    para = lambda markup, st="BodyText": Paragraph(
        markup, ss[st]
    )  # every dynamic value inside goes through _safe
    story = [
        para("TAX INVOICE", "Title"),
        Table(
            [
                [
                    para(
                        f"<b>{_safe(s['name'])}</b><br/>{_safe(s['address'])}<br/>State: {_safe(s['state'])}<br/>GSTIN: {_safe(s['gstin'] or 'not registered')}"
                    ),
                    para(
                        f"<b>Invoice no.</b> {_safe(inv.number)}<br/><b>Date</b> {timezone.localtime(inv.issued_at):%d %b %Y}<br/>"
                        f"<b>Order</b> {_safe(order.rp_order_id)}<br/><b>Payment</b> {_safe(order.rp_payment_id)}"
                    ),
                ]
            ],
            colWidths=[100 * mm, 74 * mm],
        ),
        Spacer(1, 6 * mm),
        para(
            f"<b>Bill to</b><br/>{_safe(b['name'])}<br/>{_safe(b['email'])}<br/>State (place of supply): {_safe(b['state'])}"
            + (f"<br/>GSTIN: {_safe(b['gstin'])}" if b.get("gstin") else "")
        ),
        Spacer(1, 6 * mm),
    ]
    rows = [["Description", "SAC", "Qty", "Price", "Discount", "Amount"]]
    for ln in inv.lines:
        rows.append(
            [
                para(_safe(ln["description"])),
                ln["sac"],
                ln["qty"],
                _rs(ln["list_paise"]),
                _rs(ln["discount_paise"]),
                _rs(ln["total_paise"]),
            ]
        )
    rows += [["", "", "", "", "Taxable value", _rs(inv.taxable_paise)]]
    if inv.igst_paise:
        rows.append(["", "", "", "", "IGST 18%", _rs(inv.igst_paise)])
    else:
        rows += [
            ["", "", "", "", "CGST 9%", _rs(inv.cgst_paise)],
            ["", "", "", "", "SGST 9%", _rs(inv.sgst_paise)],
        ]
    rows.append(["", "", "", "", "Total (incl. GST)", _rs(inv.total_paise)])
    t = Table(rows, colWidths=[70 * mm, 18 * mm, 10 * mm, 26 * mm, 26 * mm, 24 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1e5d6")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, len(inv.lines)), 0.4, colors.grey),
                ("FONTNAME", (4, -1), (-1, -1), "Helvetica-Bold"),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [
        t,
        Spacer(1, 8 * mm),
        para(
            "Prices include GST. This is a computer-generated invoice and needs no signature."
            + (" TEST MODE payment — no real money moved." if order.mode == "test" else "")
        ),
    ]
    doc.build(story)
    return buf.getvalue()
