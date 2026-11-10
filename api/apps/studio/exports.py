"""M6: PowerPoint (course/lesson decks for teachers) and Excel (analytics, surveys, admin overview, own progress).

Everything is streamed from memory (never stored), permission-checked like the screen it mirrors, and
spreadsheet cells can't become formulas (learner text like '=HYPERLINK(...)' stays text)."""

import io
import re
from datetime import date, datetime

from django.conf import settings
from django.http import HttpResponse

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _fname(s: str, ext: str) -> str:
    base = re.sub(r"[^\w\- ]+", "", s or "export", flags=re.UNICODE).strip()[:60] or "export"
    return f"{base}.{ext}"


def download(body: bytes, ctype: str, filename: str) -> HttpResponse:
    from urllib.parse import quote

    resp = HttpResponse(body, content_type=ctype)
    ascii_name = filename.encode("ascii", "ignore").decode() or "export"
    resp["Content-Disposition"] = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"
    resp["Cache-Control"] = "no-store"
    return resp


# ── Excel ────────────────────────────────────────────────────────────


def _cell_value(v):
    if isinstance(v, (dict, list)):
        return (
            ", ".join(f"{k}: {x}" for k, x in v.items())
            if isinstance(v, dict)
            else ", ".join(str(x) for x in v)
        )
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    return v


def workbook(sheets: list[tuple[str, list[str], list[list]]]) -> bytes:
    """sheets: [(name, header, rows)]. Strings are always stored as text (no formula evaluation)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    wb.remove(wb.active)
    used = set()
    for name, header, rows in sheets:
        title = re.sub(r"[\[\]\*\?/\\:]", "", name)[:31] or "Sheet"
        while title in used:
            title = f"{title[:28]}_{len(used)}"
        used.add(title)
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font = Font(bold=True)
        for r in rows:
            ws.append([_cell_value(v) for v in r])
        for row in ws.iter_rows(min_row=1):
            for c in row:
                if isinstance(c.value, str):
                    c.data_type = "s"  # '=...' stays literal text
        for i, h in enumerate(header, 1):
            width = max([len(str(h))] + [len(str(_cell_value(r[i - 1]))) for r in rows[:200] if len(r) >= i])
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(10, width + 2))
        ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def flatten(data, prefix="") -> tuple[list[list], list[tuple[str, list[dict]]]]:
    """Nested dict → (scalar rows [key, value], tables [(name, list-of-dicts)]) for a generic workbook."""
    scalars, tables = [], []
    for k, v in (data or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            s, t = flatten(v, f"{key}.")
            scalars += s
            tables += t
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            tables.append((key, v))
        elif isinstance(v, list):
            scalars.append([key, ", ".join(str(x) for x in v)])
        else:
            scalars.append([key, v.isoformat() if isinstance(v, (date, datetime)) else v])
    return scalars, tables


def generic_workbook(title: str, data: dict) -> bytes:
    scalars, tables = flatten(data)
    sheets = [(title, ["Metric", "Value"], scalars)]
    for name, rows in tables:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        sheets.append((name.split(".")[-1], cols, [[r.get(c) for c in cols] for r in rows]))
    return workbook(sheets)


def org_analytics_xlsx(org) -> bytes:
    from apps.orgs.api import compute_analytics

    a = compute_analytics(org)
    k = a["kpis"]
    pct = lambda v: None if v is None else round(v * 100)
    return workbook(
        [
            (
                "KPIs",
                ["Metric", "Value"],
                [
                    ["Learners", k["learners"]],
                    ["Active (7 days)", k["active_7d"]],
                    ["Lessons completed (30 days)", k["lessons_completed_30d"]],
                    ["Average score %", pct(k["avg_score"])],
                    ["Assignments", k["assignments"]],
                    ["Completion rate %", pct(k["completion_rate"])],
                ],
            ),
            (
                "Daily",
                ["Day", "XP", "Active learners"],
                [[d["day"], d["xp"], d["active"]] for d in a["daily"]],
            ),
            (
                "Assignments",
                ["Course", "Due", "Done %", "Rating", "Learners done"],
                [
                    [
                        (x["course"] or x["scenario"])["title"],
                        x.get("due_at"),
                        round((x.get("avg_pct") or 0) * 100),
                        x.get("rating"),
                        x.get("completed"),
                    ]
                    for x in a["assignments"]
                ],
            ),
            (
                "Skills",
                ["Skill", "Mastery %", "Learners"],
                [[s["name"], round(s["mastery"] * 100), s["learners"]] for s in a["skills"]],
            ),
            (
                "At risk",
                ["Learner", "Reasons", "Last active"],
                [[r["name"], ", ".join(r["reasons"]), r["last_active"]] for r in a["at_risk"]],
            ),
            (
                "Leaderboard",
                ["Learner", "XP", "Streak"],
                [[r["name"], r["xp"], r["streak"]] for r in a["leaderboard"]],
            ),
            _members_sheet(org),
        ]
    )


def _members_sheet(org):
    """Members with the org's custom fields (roll no., section…) — what teachers filter and sort by in Excel."""
    from apps.orgs.api import _first
    from apps.orgs.models import Membership

    defs = org.member_fields or []
    rows = [
        [
            _first(m.user),
            m.user.email,
            m.role,
            "yes" if m.seat else "",
            *[(m.fields or {}).get(f["key"], "") for f in defs],
            m.joined_at,
        ]
        for m in Membership.objects.filter(org=org)
        .select_related("user__profile")
        .order_by("role", "joined_at")
    ]
    return ("Members", ["Name", "Email", "Role", "Seat", *[f["label"] for f in defs], "Joined"], rows)


def survey_xlsx(s) -> bytes:
    from apps.orgs.api import _first
    from apps.orgs.surveys import all_questions, flat_answer
    from apps.orgs.surveys import results as _results

    results, _n = _results(s)
    sheets = [
        (
            "Summary",
            ["Question", "Type", "Answers", "Average", "NPS"],
            [[q["text"], q["type"], q["count"], q.get("avg"), q.get("nps")] for q in results],
        )
    ]
    for i, q in enumerate(results, 1):
        if q["type"] in ("rating", "nps", "scale"):
            rows = sorted(([k, v] for k, v in (q.get("distribution") or {}).items()), key=lambda r: r[0])
            sheets.append((f"Q{i}", ["Score", "Count"], rows))
        elif q["type"] in ("choice", "multi"):
            sheets.append((f"Q{i}", ["Option", "Count"], [[o["option"], o["count"]] for o in q["options"]]))
        elif q["type"] == "matrix":
            opts = [o["option"] for o in q["rows"][0]["options"]] if q.get("rows") else []
            sheets.append(
                (
                    f"Q{i}",
                    ["Row", *opts],
                    [[r["row"], *[o["count"] for o in r["options"]]] for r in q.get("rows", [])],
                )
            )
        else:
            sheets.append(
                (f"Q{i}", ["Answer", "Name"], [[a["text"], a["name"]] for a in q.get("answers", [])])
            )
    raw = []
    qs = all_questions(s)
    for idx, r in enumerate(s.responses.select_related("user__profile"), 1):
        who = f"#{idx}" if s.anonymous or not r.user else _first(r.user)
        raw.append([who, *[flat_answer(r.answers.get(q["id"], "")) for q in qs]])
    sheets.append(("Raw answers", ["Respondent", *[q["text"][:80] for q in qs]], raw))
    return workbook(sheets)


def progress_xlsx(user, days: int) -> bytes:
    from apps.study.progress import dashboard

    d = dashboard(user, days)
    t = d["totals"]
    return workbook(
        [
            (
                "Summary",
                ["Metric", "Value"],
                [
                    ["Days", d["days"]],
                    ["Minutes", t["minutes"]],
                    ["XP", t["xp"]],
                    ["Sessions", t["sessions"]],
                    ["Active days", t["active_days"]],
                    ["Lessons completed", t["lessons"]],
                    ["First-try accuracy %", t["first_try_accuracy"]],
                    ["Streak", t["streak"]],
                    ["Best streak", t["best_streak"]],
                ],
            ),
            (
                "Daily",
                ["Day", "Minutes", "XP"],
                [[m["label"], m["value"], x["value"]] for m, x in zip(d["minutes"], d["xp"], strict=False)],
            ),
            (
                "Skills",
                ["Skill", "Mastery %", "Practised", "Following"],
                [
                    [
                        s["name"],
                        None if s["mastery"] is None else round(s["mastery"] * 100),
                        s["usage"],
                        "yes" if s["followed"] else "",
                    ]
                    for s in d["skills"]
                ],
            ),
            (
                "Accuracy by type",
                ["Activity type", "Answers", "First-try %"],
                [[e["type"], e["attempts"], e["accuracy"]] for e in d["efficiency"]],
            ),
        ]
    )


# ── PowerPoint ───────────────────────────────────────────────────────


def _plain(md: str) -> str:
    md = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), md or "", flags=re.DOTALL)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"[*_`]{1,3}", "", md)
    return re.sub(r"^#{1,6}\s*", "", md, flags=re.MULTILINE).strip()


def _chunks(text: str, limit=650) -> list[str]:
    paras, out, cur = [p.strip() for p in text.split("\n\n") if p.strip()], [], ""
    for p in paras:
        if cur and len(cur) + len(p) > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n\n{p}".strip() if cur else p[: limit * 2]
    if cur:
        out.append(cur)
    return out or [""]


def _answer_notes(a) -> str:
    """Speaker notes: the answer + explanation (teachers see them, a projected slide doesn't)."""
    k, p, t = a.key or {}, a.payload or {}, a.type
    lines = []
    if t in ("quiz", "diagram", "slides", "viz"):
        lines.append(
            "Answer: "
            + "; ".join(
                p.get("options", [])[i] for i in k.get("correct", []) if i < len(p.get("options", []))
            )
        )
    elif t == "fill_blank":
        lines.append(
            "Answers: " + "; ".join(f"{b}: {' / '.join(v)}" for b, v in (k.get("blanks") or {}).items())
        )
    elif t == "sequencing":
        texts = {i["id"]: i["text"] for i in p.get("items", [])}
        lines.append("Correct order: " + " → ".join(texts.get(i, i) for i in k.get("order", [])))
    elif t == "matching":
        left = {i["id"]: i["text"] for i in p.get("left", [])}
        right = {i["id"]: i["text"] for i in p.get("right", [])}
        lines.append(
            "Pairs: "
            + "; ".join(f"{left.get(a_)} = {right.get(b)}" for a_, b in (k.get("pairs") or {}).items())
        )
    elif t == "categorization":
        texts = {i["id"]: i["text"] for i in p.get("items", [])}
        lines.append(
            "Groups: " + "; ".join(f"{texts.get(i, i)} → {c}" for i, c in (k.get("assign") or {}).items())
        )
    elif t in ("open_input", "task", "browser_task"):
        lines.append("Model answer: " + str(k.get("model_answer", "")))
        if k.get("rubric"):
            lines.append("Rubric: " + "; ".join(k["rubric"]))
    elif t == "code":
        lines.append("Model solution:\n" + str(k.get("model_solution", "")))
    if k.get("explanation"):
        lines.append("Why: " + k["explanation"])
    return "\n".join(lines)


def _activity_body(a) -> list[str]:
    p, t = a.payload or {}, a.type
    if t in ("quiz", "diagram", "slides", "viz"):
        return [f"{chr(65 + i)}. {o}" for i, o in enumerate(p.get("options", []))]
    if t == "fill_blank":
        return [re.sub(r"\[\[[^\]]+\]\]", "_____", p.get("text", ""))]
    if t in ("sequencing", "categorization"):
        return [i["text"] for i in p.get("items", [])] + (
            [f"Groups: {', '.join(p['categories'])}"] if p.get("categories") else []
        )
    if t == "matching":
        return [
            f"{l_['text']}   ⟷   {r['text']}"
            for l_, r in zip(p.get("left", []), p.get("right", []), strict=False)
        ]
    if t == "code":
        return [p.get("starter_code", "")[:600]]
    if t in ("task", "browser_task"):
        return [f"{i + 1}. {s}" for i, s in enumerate(p.get("steps", []))]
    if t == "decision_tree":
        node = (p.get("nodes") or {}).get(p.get("start"), {})
        return [node.get("text", "")] + [f"• {c['text']}" for c in node.get("choices", [])]
    return []


def _local_image(url: str):
    """Only our own media files are embedded (no network fetches from an export)."""
    import os

    if not url or not url.startswith(settings.MEDIA_URL):
        return None
    path = os.path.realpath(os.path.join(settings.MEDIA_ROOT, url[len(settings.MEDIA_URL) :]))
    root = os.path.realpath(settings.MEDIA_ROOT)
    return path if path.startswith(root + os.sep) and os.path.isfile(path) else None


def deck(cur, lessons=None) -> bytes:
    """Course (or selected lessons) → .pptx: title, section dividers, lesson text, key points, one slide per activity."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    title_l, content_l, section_l = prs.slide_layouts[0], prs.slide_layouts[1], prs.slide_layouts[2]

    def text_slide(title, paras, notes="", size=20):
        s = prs.slides.add_slide(content_l)
        s.shapes.title.text = title[:120]
        body = s.placeholders[1]
        body.left, body.top, body.width, body.height = Inches(0.7), Inches(1.5), Inches(11.9), Inches(5.5)
        tf = body.text_frame
        tf.clear()
        tf.word_wrap = True
        for i, ptxt in enumerate(paras or [""]):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.text = str(ptxt)[:1500]
            para.font.size = Pt(size)
        if notes:
            s.notes_slide.notes_text_frame.text = notes[:5000]
        return s

    s = prs.slides.add_slide(title_l)
    s.shapes.title.text = (cur.title or cur.goal)[:120]
    s.placeholders[1].text = (cur.description or "")[:300] or "Made with Aasan"
    lessons_by_section = {}
    for sec in cur.sections.filter(archived=False).order_by("order"):
        subs = [
            b
            for b in sec.subsections.filter(archived=False).order_by("order")
            if lessons is None or b.id in lessons
        ]
        if subs:
            lessons_by_section[sec] = subs
    for sec, subs in lessons_by_section.items():
        if lessons is None:
            d = prs.slides.add_slide(section_l)
            d.shapes.title.text = sec.title[:120]
            if len(d.placeholders) > 1:
                d.placeholders[1].text = (sec.summary or "")[:300]
        for b in subs:
            text_slide(b.title, [f"🎯 {b.objective}"] if b.objective else [], size=24)
            for i, chunk in enumerate(_chunks(_plain(b.explanation_md))):
                if chunk:
                    text_slide(f"{b.title}{f' ({i + 1})' if i else ''}", chunk.split("\n\n"), size=18)
            if b.key_points:
                text_slide("Key points", [f"• {k}" for k in b.key_points], size=22)
            for n, a in enumerate(b.activities.filter(kind="lesson").order_by("order"), 1):
                sl = text_slide(
                    f"Activity {n}: {a.title}",
                    [(a.payload or {}).get("prompt", ""), *_activity_body(a)],
                    notes=_answer_notes(a),
                    size=18,
                )
                img = _local_image((a.payload or {}).get("image", ""))
                if img:
                    try:
                        sl.shapes.add_picture(img, Inches(8.8), Inches(1.6), width=Inches(4))
                    except Exception:  # a bad image never breaks the export
                        import logging

                        logging.getLogger(__name__).info("skipped image %s", img, exc_info=True)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ── PDF table (training records) ─────────────────────────────────────

RECORDS_PDF_COLUMNS = (0, 2, 3, 6, 7, 8, 9)  # learner, type, title, completed, score, minutes, certificate


def records_pdf(title: str, header: list[str], rows: list[list]) -> bytes:
    """A landscape A4 table of training records. Every cell goes through pdf_fonts.markup (escaped: a title like
    `<img src=...>` prints as text). Shows the columns an auditor reads; the spreadsheet carries all of them."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from apps.credentials.pdf_fonts import apply, markup, plain

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=plain(title)[:200],
    )
    ss = getSampleStyleSheet()
    for st in ss.byName.values():
        apply(st)
    small = ss["BodyText"].clone("cell", fontSize=8, leading=10)
    cell = lambda v: Paragraph(markup(v, control=" "), small)
    cols = RECORDS_PDF_COLUMNS
    data = [[Paragraph(f"<b>{markup(header[i])}</b>", small) for i in cols]]
    data += [[cell(r[i] if i < len(r) else "") for i in cols] for r in rows]
    t = Table(data, colWidths=[42 * mm, 20 * mm, 78 * mm, 32 * mm, 18 * mm, 22 * mm, 40 * mm], repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1e5d6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    from django.utils import timezone

    story = [
        Paragraph(markup(title, control=" "), ss["Title"]),
        Paragraph(
            markup(f"{len(rows)} record(s) · generated {timezone.localtime():%d %b %Y %H:%M}"), ss["BodyText"]
        ),
        Spacer(1, 4 * mm),
        t if rows else Paragraph("No training records yet.", ss["BodyText"]),
    ]
    doc.build(story)
    return buf.getvalue()
