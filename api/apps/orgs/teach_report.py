"""Pilot KPI report for school/company leadership: activation, sustained use, completion, learning gain, would-recommend.
JSON for the cockpit tab, plus PDF (reportlab) and PPTX (python-pptx) exports built from the same numbers."""

import io
from collections import defaultdict
from datetime import date, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from apps.game.models import XPEvent
from apps.learning.models import LessonFeedback, Subsection, UserSubsectionState

from .models import Assignment, Survey, SurveyResponse
from .perms import require
from .teach import scope_groups, scoped_learners

MAX_DAYS = 366
DEFINITIONS = {
    "activation": "Learners who joined by the end date and started at least one lesson by then.",
    "sustained": "Learners active (earned XP) in at least 2 of the 4 weeks ending on the end date.",
    "completion": "Assigned courses finished (every lesson completed by the end date), per learner and course.",
    "gain": "Average change from pre-test to post-test on assigned courses that have checkpoint tests (post-test in range).",
    "recommend": "Share of promoters (9-10) on NPS survey questions in range; if none, share of lesson ratings of 4-5 stars.",
}


def parse_range(params) -> tuple[date, date] | None:
    today = timezone.localdate()
    try:
        end = date.fromisoformat(params.get("to")) if params.get("to") else today
        start = date.fromisoformat(params.get("from")) if params.get("from") else end - timedelta(days=89)
    except (TypeError, ValueError):
        return None
    if start > end or (end - start).days > MAX_DAYS:
        return None
    return start, end


def _rate(n, d):
    return round(n / d, 3) if d else None


def _course_done(subs_by_course, states, uid, cid) -> bool:
    subs = subs_by_course.get(cid, set())
    return bool(subs) and subs <= states.get(uid, set())


def compute_pilot(me, start: date, end: date) -> dict:
    from apps.study.models import CheckpointAttempt

    from .api import _assignment_learners

    org = me.org
    learners = list(scoped_learners(me).filter(joined_at__date__lte=end))
    uids = [m.user_id for m in learners]
    n = len(uids)

    # Activation: joined → started a first lesson (any course).
    started = set(
        UserSubsectionState.objects.filter(user_id__in=uids)
        .filter(Q(started_at__date__lte=end) | Q(completed_at__date__lte=end))
        .values_list("user_id", flat=True)
    )
    joined_in_range = sum(1 for m in learners if start <= timezone.localtime(m.joined_at).date() <= end)

    # Sustained use: active in ≥2 of the last 4 weeks (ending on `end`).
    w0 = end - timedelta(days=27)
    weeks_by_user = defaultdict(set)
    for uid, day in (
        XPEvent.objects.filter(user_id__in=uids, day__gte=w0, day__lte=end)
        .values_list("user_id", "day")
        .distinct()
    ):
        weeks_by_user[uid].add((day - w0).days // 7)
    sustained = sum(1 for u in uids if len(weeks_by_user[u]) >= 2)

    # Completion of assigned courses.
    uidset = set(uids)
    course_assigns = list(
        Assignment.objects.filter(
            org=org, curriculum__isnull=False, created_at__date__lte=end
        ).select_related("curriculum")
    )
    cids = {a.curriculum_id for a in course_assigns}
    subs_by_course = defaultdict(set)
    for sid, cid in Subsection.objects.filter(
        section__curriculum_id__in=cids, archived=False, section__archived=False
    ).values_list("id", "section__curriculum_id"):
        subs_by_course[cid].add(sid)
    states = defaultdict(set)
    for uid, sid in UserSubsectionState.objects.filter(
        user_id__in=uids,
        subsection__section__curriculum_id__in=cids,
        status="completed",
        completed_at__date__lte=end,
    ).values_list("user_id", "subsection_id"):
        states[uid].add(sid)
    pairs, per_course = set(), {}
    for a in course_assigns:
        aud = set(_assignment_learners(a).values_list("user_id", flat=True)) & uidset
        for u in aud:
            pairs.add((u, a.curriculum_id))
        c = per_course.setdefault(a.curriculum_id, {"title": a.curriculum.title, "learners": set()})
        c["learners"] |= aud
    completed_pairs = sum(1 for u, cid in pairs if _course_done(subs_by_course, states, u, cid))
    courses = [
        {
            "title": c["title"],
            "learners": len(c["learners"]),
            "completed": sum(1 for u in c["learners"] if _course_done(subs_by_course, states, u, cid)),
            "rate": _rate(
                sum(1 for u in c["learners"] if _course_done(subs_by_course, states, u, cid)),
                len(c["learners"]),
            ),
        }
        for cid, c in per_course.items()
    ]

    # Learning gain: first pre-test vs latest post-test (in range) per learner and assigned course.
    pre, post = {}, {}
    for at in CheckpointAttempt.objects.filter(user_id__in=uids, curriculum_id__in=cids).order_by(
        "created_at", "id"
    ):
        k = (at.user_id, at.curriculum_id)
        if at.kind == "pre" and k not in pre and at.total:
            pre[k] = at.correct / at.total
        elif at.kind == "post" and at.total and start <= timezone.localtime(at.created_at).date() <= end:
            post[k] = at.correct / at.total
    both = [k for k in post if k in pre]
    gain = {
        "pairs": len(both),
        "avg_pre": _rate(sum(pre[k] for k in both), len(both)),
        "avg_post": _rate(sum(post[k] for k in both), len(both)),
        "avg_gain": _rate(sum(post[k] - pre[k] for k in both), len(both)),
    }

    # Would recommend: NPS questions in org surveys, else lesson ratings ≥ 4.
    g = scope_groups(me)
    surveys = Survey.objects.filter(org=org)
    if g is not None:
        surveys = surveys.filter(Q(group__isnull=True) | Q(group_id__in=g))
    nps_vals = []
    for s in surveys:
        qids = [q["id"] for q in s.questions if q.get("type") == "nps"]
        if not qids:
            continue
        for ans in SurveyResponse.objects.filter(
            survey=s, submitted_at__date__gte=start, submitted_at__date__lte=end
        ).values_list("answers", flat=True):
            for q in qids:
                v = (ans or {}).get(q)
                if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                    nps_vals.append(int(v))
    promoters, detractors = sum(v >= 9 for v in nps_vals), sum(v <= 6 for v in nps_vals)
    ratings = list(
        LessonFeedback.objects.filter(
            user_id__in=uids,
            subsection__section__curriculum_id__in=cids,
            created_at__date__gte=start,
            created_at__date__lte=end,
        ).values_list("rating", flat=True)
    )
    recommend = {
        "nps_responses": len(nps_vals),
        "nps": round(100 * (promoters - detractors) / len(nps_vals)) if nps_vals else None,
        "promoters": _rate(promoters, len(nps_vals)),
        "ratings": len(ratings),
        "rating_4plus": _rate(sum(r >= 4 for r in ratings), len(ratings)),
    }
    recommend["value"] = recommend["promoters"] if nps_vals else recommend["rating_4plus"]
    recommend["source"] = "nps" if nps_vals else "ratings" if ratings else None

    # Weekly series for charts (at most 26 bars; the last week ends on `end`).
    weeks = []
    first = max(start, end - timedelta(days=7 * 26 - 1))
    ws = end - timedelta(days=6)
    while ws + timedelta(days=6) >= first and len(weeks) < 26:
        weeks.append(max(ws, first))
        ws -= timedelta(days=7)
    weeks.reverse()
    act = defaultdict(set)
    for uid, day in (
        XPEvent.objects.filter(user_id__in=uids, day__gte=first, day__lte=end)
        .values_list("user_id", "day")
        .distinct()
    ):
        idx = max(i for i, w in enumerate(weeks) if w <= day)
        act[idx].add(uid)
    lessons = defaultdict(int)
    for d in UserSubsectionState.objects.filter(
        user_id__in=uids, status="completed", completed_at__date__gte=first, completed_at__date__lte=end
    ).values_list("completed_at", flat=True):
        day = timezone.localtime(d).date()
        lessons[max(i for i, w in enumerate(weeks) if w <= day)] += 1
    weekly = [{"week": w, "active": len(act[i]), "lessons": lessons[i]} for i, w in enumerate(weeks)]

    return {
        "org": org.display_name or org.name,
        "from": start,
        "to": end,
        "no_class": scope_groups(me) == set(),
        "kpis": {
            "learners": n,
            "joined_in_range": joined_in_range,
            "activation": {"value": _rate(len(started & uidset), n), "n": len(started & uidset), "of": n},
            "sustained": {"value": _rate(sustained, n), "n": sustained, "of": n},
            "completion": {
                "value": _rate(completed_pairs, len(pairs)),
                "n": completed_pairs,
                "of": len(pairs),
            },
            "gain": gain,
            "recommend": recommend,
        },
        "weekly": weekly,
        "courses": sorted(courses, key=lambda c: -(c["rate"] or 0)),
        "definitions": DEFINITIONS,
    }


def _pct(v):
    return "—" if v is None else f"{round(v * 100)}%"


def _n(count, word: str) -> str:
    """'1 learner', '3 learners' (English report text)."""
    return f"{count} {word}" if abs(count) == 1 else f"{count} {word}s"


def highlights(d) -> list[str]:
    k = d["kpis"]
    out = [
        f"{k['activation']['n']} of {_n(k['activation']['of'], 'learner')} started learning ({_pct(k['activation']['value'])} activation).",
        f"{_n(k['sustained']['n'], 'learner')} kept going in at least 2 of the last 4 weeks ({_pct(k['sustained']['value'])}).",
        f"{k['completion']['n']} of {_n(k['completion']['of'], 'assigned course enrolment')} finished ({_pct(k['completion']['value'])}).",
    ]
    g = k["gain"]
    if g["pairs"]:
        out.append(
            f"Test scores went from {_pct(g['avg_pre'])} to {_pct(g['avg_post'])} on average "
            f"({'+' if g['avg_gain'] >= 0 else ''}{_n(round(g['avg_gain'] * 100), 'point')}, {_n(g['pairs'], 'learner')} with both tests)."
        )
    r = k["recommend"]
    if r["source"] == "nps":
        out.append(
            f"NPS {r['nps']} from {_n(r['nps_responses'], 'answer')}; {_pct(r['promoters'])} would recommend."
        )
    elif r["source"] == "ratings":
        out.append(
            f"{_pct(r['rating_4plus'])} of {_n(r['ratings'], 'lesson rating')} {'was' if r['ratings'] == 1 else 'were'} 4 or 5 stars."
        )
    best = next((c for c in d["courses"] if c["learners"]), None)
    if best:
        out.append(f"Most completed course: {best['title']} ({_pct(best['rate'])}).")
    return out


KPI_LABELS = [("activation", "Activation"), ("sustained", "Sustained use"), ("completion", "Completion")]


def _tiles(d) -> list[tuple[str, str, str]]:
    k = d["kpis"]
    g, r = k["gain"], k["recommend"]
    tiles = [(label, _pct(k[key]["value"]), f"{k[key]['n']} of {k[key]['of']}") for key, label in KPI_LABELS]
    tiles.append(
        (
            "Learning gain",
            "—"
            if g["avg_gain"] is None
            else f"{'+' if g['avg_gain'] >= 0 else ''}{round(g['avg_gain'] * 100)} pts",
            f"{_n(g['pairs'], 'learner')} with pre + post test",
        )
    )
    tiles.append(
        (
            "Would recommend",
            _pct(r["value"]),
            f"NPS {r['nps']}" if r["source"] == "nps" else _n(r["ratings"], "lesson rating"),
        )
    )
    return tiles


# ── PDF ───────────────────────────────────────────────────────────────


def render_pdf(d) -> bytes:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from apps.billing.invoices import _safe
    from apps.credentials.pdf_fonts import apply

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Pilot report",
    )
    ss = getSampleStyleSheet()
    for st in ss.byName.values():
        apply(st)
    P = lambda markup, st="BodyText": Paragraph(markup, ss[st])
    story = [
        P(f"Pilot report: {_safe(d['org'])}", "Title"),
        P(f"{d['from']:%d %b %Y} to {d['to']:%d %b %Y} · {_n(d['kpis']['learners'], 'learner')}"),
        Spacer(1, 5 * mm),
    ]
    tiles = _tiles(d)
    t = Table(
        [
            [P(f"<b>{_safe(lbl)}</b>") for lbl, _, _ in tiles],
            [P(f"<font size=18><b>{_safe(v)}</b></font>") for _, v, _ in tiles],
            [P(f"<font size=8>{_safe(s)}</font>") for _, _, s in tiles],
        ],
        colWidths=[35 * mm] * 5,
    )
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1e5d6")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story += [t, Spacer(1, 6 * mm), P("<b>Active learners per week</b>")]
    weekly = d["weekly"] or [{"week": d["to"], "active": 0, "lessons": 0}]
    dr = Drawing(170 * mm, 60 * mm)
    ch = VerticalBarChart()
    ch.x, ch.y, ch.width, ch.height = 10 * mm, 10 * mm, 155 * mm, 45 * mm
    ch.data = [[w["active"] for w in weekly], [w["lessons"] for w in weekly]]
    ch.categoryAxis.categoryNames = [f"{w['week']:%d %b}" for w in weekly]
    ch.categoryAxis.labels.fontSize = 6
    ch.categoryAxis.labels.angle = 45 if len(weekly) > 8 else 0
    ch.valueAxis.valueMin = 0
    ch.bars[0].fillColor = colors.HexColor("#d97706")
    ch.bars[1].fillColor = colors.HexColor("#94a3b8")
    dr.add(ch)
    story += [
        dr,
        P("<font size=8>Orange: active learners · grey: lessons completed</font>"),
        Spacer(1, 4 * mm),
    ]
    if d["courses"]:
        rows = [["Course", "Learners", "Finished", "Rate"]] + [
            [P(_safe(c["title"])), c["learners"], c["completed"], _pct(c["rate"])] for c in d["courses"][:20]
        ]
        ct = Table(rows, colWidths=[100 * mm, 22 * mm, 22 * mm, 22 * mm])
        ct.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1e5d6")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ]
            )
        )
        story += [P("<b>Assigned courses</b>"), ct, Spacer(1, 4 * mm)]
    story.append(P("<b>Highlights</b>"))
    story += [P(f"• {_safe(h)}") for h in highlights(d)]
    story += [Spacer(1, 4 * mm), P("<b>How we measure</b>")]
    story += [P(f"<font size=8><b>{_safe(k)}</b>: {_safe(v)}</font>") for k, v in d["definitions"].items()]
    doc.build(story)
    return buf.getvalue()


# ── PPTX ──────────────────────────────────────────────────────────────


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

    s = prs.slides.add_slide(blank)
    text(s, 0.8, 2.4, 11.5, 1.2, "Pilot report", 44, True, accent)
    text(s, 0.8, 3.6, 11.5, 1.0, d["org"], 30, True)
    text(
        s,
        0.8,
        4.6,
        11.5,
        0.8,
        f"{d['from']:%d %b %Y} – {d['to']:%d %b %Y} · {_n(d['kpis']['learners'], 'learner')}",
        18,
        color=muted,
    )

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Key results", 32, True)
    for i, (label, value, sub) in enumerate(_tiles(d)):
        x = 0.6 + i * 2.45
        box = s.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(1.8), Inches(2.25), Inches(2.6)
        )
        box.fill.solid()
        box.fill.fore_color.rgb = RGBColor(0xFD, 0xF3, 0xE7)
        box.line.color.rgb = accent
        text(s, x + 0.1, 1.95, 2.05, 0.6, label, 14, True, muted)
        text(s, x + 0.1, 2.6, 2.05, 1.0, value, 34, True, accent)
        text(s, x + 0.1, 3.6, 2.05, 0.7, sub, 11, color=muted)

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Active learners per week", 32, True)
    weekly = d["weekly"]
    top = max([w["active"] for w in weekly] + [1])
    chart_h, base_y = 4.6, 6.4
    bw = min(0.9, 11.6 / max(1, len(weekly)))
    for i, w in enumerate(weekly):
        h = chart_h * w["active"] / top
        x = 0.8 + i * bw
        if h > 0:
            bar = s.shapes.add_shape(
                MSO_SHAPE.RECTANGLE, Inches(x + 0.05), Inches(base_y - h), Inches(bw - 0.1), Inches(h)
            )
            bar.fill.solid()
            bar.fill.fore_color.rgb = accent
            bar.line.fill.background()
        text(s, x, base_y - h - 0.4, bw, 0.35, w["active"], 10, True)
        text(s, x, base_y + 0.05, bw, 0.4, f"{w['week']:%d %b}", 8, color=muted)

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Assigned courses", 32, True)
    rows = d["courses"][:12]
    if rows:
        tbl = s.shapes.add_table(
            len(rows) + 1, 4, Inches(0.6), Inches(1.5), Inches(12), Inches(0.4 * (len(rows) + 1))
        ).table
        for j, h in enumerate(["Course", "Learners", "Finished", "Rate"]):
            tbl.cell(0, j).text = h
        for i, c in enumerate(rows, 1):
            for j, v in enumerate([c["title"], c["learners"], c["completed"], _pct(c["rate"])]):
                tbl.cell(i, j).text = str(v)
        tbl.columns[0].width = Inches(7.5)
    else:
        text(s, 0.6, 1.6, 12, 0.8, "No courses assigned in this period.", 18, color=muted)

    s = prs.slides.add_slide(blank)
    text(s, 0.6, 0.4, 12, 0.8, "Highlights", 32, True)
    tb = s.shapes.add_textbox(Inches(0.8), Inches(1.5), Inches(11.8), Inches(5.5))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, h in enumerate(highlights(d)):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"• {h}"
        for r in p.runs:
            r.font.size = Pt(20)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


# ── Views ─────────────────────────────────────────────────────────────


def _report(request, slug):
    me = require(request.user, slug, "manager")
    rng = parse_range(request.query_params)
    if not rng:
        return None, Response({"code": "bad_range"}, status=status.HTTP_400_BAD_REQUEST)
    return compute_pilot(me, *rng), None


@api_view(["GET"])
def pilot(request, slug):
    d, bad = _report(request, slug)
    return bad or Response({**d, "highlights": highlights(d)})


@api_view(["GET"])
def pilot_pdf(request, slug):
    from apps.studio import exports

    d, bad = _report(request, slug)
    if bad:
        return bad
    return exports.download(
        render_pdf(d), "application/pdf", exports._fname(f"{d['org']} pilot report", "pdf")
    )


@api_view(["GET"])
def pilot_pptx(request, slug):
    from apps.studio import exports

    d, bad = _report(request, slug)
    if bad:
        return bad
    return exports.download(render_pptx(d), exports.PPTX, exports._fname(f"{d['org']} pilot report", "pptx"))
