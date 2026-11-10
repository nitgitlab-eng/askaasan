"""The post-run report for an institution workshop run, in the style of the orgs pilot report (teach_report): JSON for
the cockpit, PDF (reportlab, Noto fonts for Tamil names), PPTX (python-pptx) and a per-student CSV (csv_safe).
Everything is computed over the learners the viewer may see: teachers get their own classes only."""

import csv
import io
from collections import Counter, defaultdict

from django.utils import timezone

from . import services
from .models import WorkshopEvent, WorkshopSession

BUCKETS = ((0, 20), (20, 40), (40, 60), (60, 80), (80, 101))
TOP = 10
HELP_EVENTS = ("help_screenshot", "help_error")


def _rate(n, d):
    return round(n / d, 3) if d else None


def _pct(v):
    return "—" if v is None else f"{round(v * 100)}%"


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def _status(s) -> str:
    if s is None:
        return "not_joined"
    if s.passed:
        return "passed"
    if s.status == WorkshopSession.Status.SUBMITTED:
        return "finished"
    return "in_progress" if s.started_at else "getting_ready"


STATUS_LABEL = {
    "not_joined": "Not joined",
    "getting_ready": "Getting ready",
    "in_progress": "In progress",
    "finished": "Finished",
    "passed": "Passed",
}


def compute(me, run) -> dict:
    from apps.orgs.models import Membership

    from .monitor import _norm, learner_out
    from .org import enrolled_ids, scope_user_ids, stage_times

    scope = scope_user_ids(me)
    uids = enrolled_ids(run, scope)
    w = run.workshop
    agenda = w.agenda or []
    proctoring = run.effective_proctoring != "off"
    sessions = {
        s.user_id: s
        for s in WorkshopSession.objects.filter(run=run, user_id__in=uids).select_related("user__profile")
    }
    from apps.accounts.models import User

    users = {u.id: u for u in User.objects.filter(id__in=uids).select_related("profile")}
    members = {m.user_id: m for m in Membership.objects.filter(org=run.org, user_id__in=uids)}
    events_by = defaultdict(list)
    for e in WorkshopEvent.objects.filter(session__in=[s.id for s in sessions.values()]).exclude(
        type="ai_turn"
    ):
        events_by[e.session_id].append(e)
    for evs in events_by.values():
        evs.sort(key=lambda e: (e.created_at, e.id))

    n = len(uids)
    joined = [s for s in sessions.values()]
    started = [s for s in joined if s.started_at]
    finished = [s for s in joined if s.status == WorkshopSession.Status.SUBMITTED]
    passed = [s for s in joined if s.passed]
    finals = [s.final_score for s in joined if s.final_score is not None]
    distribution = [
        {"range": f"{lo}-{min(hi, 100)}", "count": sum(1 for v in finals if lo <= round(v * 100) < hi)}
        for lo, hi in BUCKETS
    ]

    # Per stage: average score and minutes spent (over learners who reached it).
    times = {}
    for s in started:
        evs = events_by.get(s.id, [])
        times[s.id] = stage_times(evs, s.ended_at or (evs[-1].created_at if evs else None))
    stages = []
    for i, st in enumerate(agenda):
        key = st.get("key", str(i))
        spent = [t[i] for t in times.values() if i in t]
        stages.append(
            {
                "index": i,
                "title": st.get("title", ""),
                "kind": st.get("kind", ""),
                "avg_score": _avg([(s.scores or {}).get(key) for s in started]),
                "avg_minutes": round(sum(spent) / len(spent) / 60, 1) if spent else None,
                "reached": len(spent),
            }
        )

    # Most-missed concepts (check answers under the pass bar) and help topics (the AI's summaries only).
    missed = Counter()
    missed_by = defaultdict(set)
    helps = Counter()
    help_text = {}
    for s in joined:
        for e in events_by.get(s.id, []):
            d = e.data or {}
            if e.type == "answer" and isinstance(d.get("score"), int | float) and d["score"] < services.PASS:
                texts = services.item_texts(agenda[e.stage]) if 0 <= e.stage < len(agenda) else []
                item = d.get("item")
                if isinstance(item, int) and 0 <= item < len(texts):
                    missed[(e.stage, item)] += 1
                    missed_by[(e.stage, item)].add(s.user_id)
            elif e.type in HELP_EVENTS and d.get("summary"):
                k = _norm(d["summary"])
                helps[k] += 1
                help_text.setdefault(k, d["summary"])
    missed_out = [
        {
            "concept": services.item_texts(agenda[st])[item],
            "stage": agenda[st].get("title", ""),
            "misses": c,
            "learners": len(missed_by[(st, item)]),
        }
        for (st, item), c in missed.most_common(TOP)
    ]
    help_out = [{"topic": help_text[k], "count": c} for k, c in helps.most_common(TOP)]

    attention = None
    if proctoring:
        attention = {
            "avg_attention": _avg([s.attention_score for s in started]),
            "avg_hidden_minutes": round(sum(s.hidden_seconds for s in started) / len(started) / 60, 1)
            if started
            else None,
            "focus_losses": sum(s.focus_losses for s in started),
        }

    rows = []
    for uid in uids:
        u, s, m = users.get(uid), sessions.get(uid), members.get(uid)
        if not u:
            continue
        who = learner_out(u, m)
        minutes = None
        if s and s.started_at:
            end = s.ended_at or ((events_by.get(s.id) or [None])[-1] or s).created_at
            minutes = round(max(0.0, (end - s.started_at).total_seconds()) / 60, 1)
        evs = events_by.get(s.id, []) if s else []
        rows.append(
            {
                "name": who["name"],
                "roll_no": who.get("roll_no", ""),
                "email": u.email,
                "status": _status(s),
                "final_score": s.final_score if s else None,
                "passed": bool(s and s.passed),
                "minutes": minutes,
                "help_requests": sum(1 for e in evs if e.type in HELP_EVENTS),
                "stage_scores": [
                    (s.scores or {}).get(st.get("key", str(i))) if s else None for i, st in enumerate(agenda)
                ],
                **(
                    {
                        "focus_losses": s.focus_losses if s else 0,
                        "hidden_minutes": round((s.hidden_seconds if s else 0) / 60, 1),
                        "attention": s.attention_score if s else None,
                    }
                    if proctoring
                    else {}
                ),
            }
        )
    rows.sort(key=lambda r: (r["roll_no"] or "~", r["name"].casefold()))

    return {
        "org": run.org.display_name or run.org.name,
        "run": {
            "id": run.id,
            "workshop": w.title,
            "starts_at": run.starts_at,
            "status": run.effective_status(services.now()),
            "proctoring": run.effective_proctoring,
            "pass_mark": w.pass_mark,
        },
        "scope": "all" if scope is None else "classes",
        "participation": {
            "enrolled": n,
            "joined": len(joined),
            "started": len(started),
            "finished": len(finished),
            "passed": len(passed),
            "join_rate": _rate(len(joined), n),
            "completion_rate": _rate(len(finished), n),
            "pass_rate": _rate(len(passed), n),
            "pass_rate_of_finished": _rate(len(passed), len(finished)),
        },
        "scores": {"avg": _avg(finals), "distribution": distribution},
        "stages": stages,
        "missed_concepts": missed_out,
        "help_topics": help_out,
        "attention": attention,
        "students": rows,
        "generated_at": timezone.now(),
    }


def filename(d) -> str:
    return f"{d['run']['workshop']} workshop report"


def _end(text) -> str:
    """A sentence ending in exactly one full stop (AI help summaries usually bring their own: no "formula..")."""
    return str(text).rstrip(" .") + "."


def highlights(d) -> list[str]:
    p = d["participation"]
    out = [
        (
            f"{p['joined']} of {p['enrolled']} enrolled learners joined; {p['finished']} finished "
            f"({_pct(p['completion_rate'])}) and {p['passed']} passed ({_pct(p['pass_rate'])})."
        )
    ]
    if d["scores"]["avg"] is not None:
        out.append(f"Average final score: {_pct(d['scores']['avg'])}.")
    if d["missed_concepts"]:
        m = d["missed_concepts"][0]
        out.append(f"Most missed: {str(m['concept']).rstrip(' .')} ({m['learners']} learners).")
    if d["help_topics"]:
        out.append(_end(f"Top help topic: {d['help_topics'][0]['topic']}"))
    a = d["attention"]
    if a and a["avg_attention"] is not None:
        out.append(
            f"Average attention: {_pct(a['avg_attention'])} ({a['focus_losses']} focus losses in all)."
        )
    return out


def _tiles(d) -> list[tuple[str, str, str]]:
    p = d["participation"]
    return [
        ("Joined", f"{p['joined']}/{p['enrolled']}", _pct(p["join_rate"])),
        ("Completion", _pct(p["completion_rate"]), f"{p['finished']} finished"),
        ("Pass rate", _pct(p["pass_rate"]), f"{p['passed']} passed"),
        ("Avg score", _pct(d["scores"]["avg"]), f"pass mark {_pct(d['run']['pass_mark'])}"),
    ]


def _when(d) -> str:
    return f"{timezone.localtime(d['run']['starts_at']):%d %b %Y, %I:%M %p}"


# ── CSV ──────────────────────────────────────────────────────────────


def csv_rows(d) -> tuple[list, list[list]]:
    proctoring = d["attention"] is not None
    header = ["Name", "Roll no", "Email", "Status", "Final score %", "Passed", "Minutes", "Help requests"]
    if proctoring:
        header += ["Focus losses", "Hidden minutes", "Attention %"]
    header += [f"Stage {s['index'] + 1}: {s['title']} %" for s in d["stages"]]
    rows = []
    for r in d["students"]:
        row = [
            r["name"],
            r["roll_no"],
            r["email"],
            STATUS_LABEL[r["status"]],
            "" if r["final_score"] is None else round(r["final_score"] * 100),
            "yes" if r["passed"] else "no",
            "" if r["minutes"] is None else r["minutes"],
            r["help_requests"],
        ]
        if proctoring:
            row += [
                r["focus_losses"],
                r["hidden_minutes"],
                "" if r["attention"] is None else round(r["attention"] * 100),
            ]
        row += ["" if v is None else round(v * 100) for v in r["stage_scores"]]
        rows.append(row)
    return header, rows


def render_csv(d) -> str:
    """Every cell (headers too) is formula-safe: names, stage titles and roll numbers are user / author text."""
    from apps.orgs.csvsafe import csv_safe

    header, rows = csv_rows(d)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([csv_safe(v) for v in header])
    for r in rows:
        w.writerow([csv_safe(v) for v in r])
    return buf.getvalue()


# ── PDF ──────────────────────────────────────────────────────────────


def render_pdf(d) -> bytes:
    """Every cell is a Paragraph in the Noto family (when installed), so Tamil names and summaries draw everywhere."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from apps.billing.invoices import _safe
    from apps.credentials.pdf_fonts import apply, fonts

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title="Workshop report",
    )
    ss = getSampleStyleSheet()
    noto = fonts()
    for st in ss.byName.values():
        apply(st)
        if noto and hasattr(st, "fontName"):  # Noto even without HarfBuzz, so every table shares one family
            st.fontName = noto["base"][1] if "Bold" in st.fontName else noto["base"][0]
    body = ss["BodyText"]

    def style(name, size, bold=False, lead=1.25):
        st = ParagraphStyle(name, parent=body, fontSize=size, leading=round(size * lead, 1))
        if bold:
            st.fontName = noto["base"][1] if noto else "Helvetica-Bold"
        return st

    cell, head_st, small = style("cell", 9), style("head", 9, bold=True), style("small", 7)
    small_head = style("small_head", 7, bold=True)
    kpi_label, kpi_value, kpi_sub = (
        style("kpi_label", 9, bold=True),
        style("kpi_value", 18, True),
        style("kpi_sub", 8),
    )

    def P(markup, st="BodyText"):
        return Paragraph(markup, ss[st] if isinstance(st, str) else st)

    def C(v, st=cell):
        return Paragraph(_safe("" if v is None else v), st)

    head = colors.HexColor("#f1e5d6")
    grid = [
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), head),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]

    def table(header, rows, widths, hs=head_st, cs=cell, repeat=0):
        t = Table(
            [[C(h, hs) for h in header]] + [[C(v, cs) for v in r] for r in rows],
            colWidths=widths,
            repeatRows=repeat,
        )
        t.setStyle(TableStyle(grid))
        return t

    story = [
        P(f"Workshop report: {_safe(d['run']['workshop'])}", "Title"),
        P(f"{_safe(d['org'])} · {_safe(_when(d))} · {d['participation']['enrolled']} learners"),
        Spacer(1, 4 * mm),
    ]
    tiles = _tiles(d)
    t = Table(
        [
            [C(lbl, kpi_label) for lbl, _, _ in tiles],
            [C(v, kpi_value) for _, v, _ in tiles],
            [C(s, kpi_sub) for _, _, s in tiles],
        ],
        colWidths=[45 * mm] * 4,
    )
    # One box per tile (no rules between the label, the number and the note), so the big number never sits on a line.
    t.setStyle(
        TableStyle(
            [("BOX", (i, 0), (i, -1), 0.3, colors.grey) for i in range(len(tiles))]
            + [
                ("BACKGROUND", (0, 0), (-1, 0), head),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 1), (-1, 1), 6),
            ]
        )
    )
    story += [t, Spacer(1, 4 * mm), P("<b>Highlights</b>")]
    story += [P(f"• {_safe(h)}") for h in highlights(d)]
    dist = d["scores"]["distribution"]
    story += [Spacer(1, 3 * mm), P("<b>Final score distribution</b>")]
    story += [table([x["range"] for x in dist], [[x["count"] for x in dist]], [30 * mm] * len(dist))]
    story += [Spacer(1, 3 * mm), P("<b>Stages</b>")]
    story.append(
        table(
            ["Stage", "Kind", "Reached", "Avg score", "Avg minutes"],
            [
                [
                    s["title"],
                    s["kind"],
                    s["reached"],
                    _pct(s["avg_score"]),
                    "—" if s["avg_minutes"] is None else s["avg_minutes"],
                ]
                for s in d["stages"]
            ],
            [80 * mm, 25 * mm, 22 * mm, 25 * mm, 28 * mm],
        )
    )
    if d["missed_concepts"]:
        mt = table(
            ["Concept", "Stage", "Misses", "Learners"],
            [[m["concept"], m["stage"], m["misses"], m["learners"]] for m in d["missed_concepts"]],
            [85 * mm, 55 * mm, 20 * mm, 20 * mm],
        )
        story += [Spacer(1, 3 * mm), P("<b>Most-missed concepts</b>"), mt]
    if d["help_topics"]:
        ht = table(
            ["Help topic (AI summary)", "Requests"],
            [[h["topic"], h["count"]] for h in d["help_topics"]],
            [155 * mm, 25 * mm],
        )
        story += [Spacer(1, 3 * mm), P("<b>Help topics</b>"), ht]
    a = d["attention"]
    if a:
        story += [
            Spacer(1, 3 * mm),
            P("<b>Attention (proctoring on; paused during hands-on stages)</b>"),
            P(
                f"Average attention {_pct(a['avg_attention'])} · average time away "
                f"{'—' if a['avg_hidden_minutes'] is None else a['avg_hidden_minutes']} min · "
                f"{a['focus_losses']} focus losses"
            ),
        ]
    header, rows = csv_rows(d)
    keep = [j for j, h in enumerate(header[: 8 + (3 if a else 0)]) if h != "Email"]
    # The name gets room of its own: a long (Tamil) name split mid-word breaks its letter clusters.
    name_w = 40 * mm
    rest = (182 * mm - name_w) / max(1, len(keep) - 1)
    pt = table(
        [header[j] for j in keep],
        [[r[j] for j in keep] for r in rows],
        [name_w] + [rest] * (len(keep) - 1),
        hs=small_head,
        cs=small,
        repeat=1,
    )
    story += [Spacer(1, 4 * mm), P("<b>Students</b>"), pt]
    doc.build(story)
    return buf.getvalue()


# ── PPTX ─────────────────────────────────────────────────────────────


def render_pptx(d) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    accent, ink, muted = RGBColor(0xD9, 0x77, 0x06), RGBColor(0x1F, 0x29, 0x37), RGBColor(0x64, 0x74, 0x8B)

    def text(slide, x, y, w, h, s, size=18, bold=False, color=ink):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.text = str(s)
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.size, r.font.bold, r.font.color.rgb = Pt(size), bold, color
        return tb

    def table(slide, header, rows, top=1.5, first_col=6.0):
        tbl = slide.shapes.add_table(
            len(rows) + 1, len(header), Inches(0.6), Inches(top), Inches(12), Inches(0.4 * (len(rows) + 1))
        ).table
        for j, h in enumerate(header):
            tbl.cell(0, j).text = str(h)
        for i, r in enumerate(rows, 1):
            for j, v in enumerate(r):
                tbl.cell(i, j).text = "" if v is None else str(v)
        tbl.columns[0].width = Inches(first_col)

    s = prs.slides.add_slide(blank)
    text(s, 0.8, 2.2, 11.5, 1.2, "Workshop report", 44, True, accent)
    text(s, 0.8, 3.4, 11.5, 1.0, d["run"]["workshop"], 30, True)
    text(s, 0.8, 4.4, 11.5, 0.8, f"{d['org']} · {_when(d)}", 18, color=muted)

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Key results", 32, True)
    for i, (label, value, sub) in enumerate(_tiles(d)):
        x = 0.6 + i * 3.05
        box = s.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.6), Inches(2.85), Inches(2.4)
        )
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(0xFD, 0xF3, 0xE7)
        box.line.color.rgb = accent
        text(s, x + 0.1, 1.75, 2.65, 0.6, label, 14, True, muted)
        text(s, x + 0.1, 2.35, 2.65, 1.0, value, 32, True, accent)
        text(s, x + 0.1, 3.35, 2.65, 0.6, sub, 12, color=muted)
    tb = s.shapes.add_textbox(Inches(0.8), Inches(4.4), Inches(11.8), Inches(2.8))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, h in enumerate(highlights(d)):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"• {h}"
        for r in p.runs:
            r.font.size = Pt(16)

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Stages", 32, True)
    table(
        s,
        ["Stage", "Kind", "Reached", "Avg score", "Avg minutes"],
        [
            [x["title"], x["kind"], x["reached"], _pct(x["avg_score"]), x["avg_minutes"] or "—"]
            for x in d["stages"][:12]
        ],
    )

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Where learners needed help", 32, True)
    if d["missed_concepts"] or d["help_topics"]:
        rows = [[m["concept"], f"missed by {m['learners']}"] for m in d["missed_concepts"][:6]]
        rows += [[h["topic"], f"{h['count']} help requests"] for h in d["help_topics"][:6]]
        table(s, ["Concept / help topic", "How many"], rows, first_col=9.0)
    else:
        text(s, 0.6, 1.6, 12, 0.8, "No missed concepts or help requests.", 18, color=muted)

    header, rows = csv_rows(d)
    keep = [j for j, h in enumerate(header[: 8 + (3 if d["attention"] else 0)]) if h != "Email"]
    per = 14
    for start in range(0, max(1, len(rows)), per):
        s = prs.slides.add_slide(blank)
        text(
            s, 0.6, 0.4, 12, 0.8, "Students" + (f" ({start // per + 1})" if len(rows) > per else ""), 32, True
        )
        chunk = rows[start : start + per]
        if chunk:
            table(s, [header[j] for j in keep], [[r[j] for j in keep] for r in chunk], top=1.3, first_col=3.0)
        else:
            text(s, 0.6, 1.6, 12, 0.8, "No learners in this report.", 18, color=muted)
        if start // per >= 20:  # a very large batch: the CSV has everyone
            break
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
