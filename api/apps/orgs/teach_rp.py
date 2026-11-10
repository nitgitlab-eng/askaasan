"""Role-play competency analytics (M10 rca) for one assigned scenario: a learners × concepts matrix (best level each
learner reached per objective / competency, with column pass rates), the assigned → started → completed → passed funnel,
"stuck learner" flags with reasons, and a per-concept drill-down of what the live coach and the final evaluator said.

Concepts: the scenario's objectives (live coach scores them 0-3 every learner turn; the final evaluator marks them met)
and its competencies (final evaluator scores 1-5). Only attempts started for THIS assignment count (teach._sessions)."""

import re
import unicodedata
from collections import Counter, defaultdict
from datetime import timedelta

from llm.fence import fence

PASS_SCORE = 70  # overall /100 counted as "passed" in the funnel
OBJ_MAX, OBJ_PASS = (
    3,
    3,
)  # coach: 0 not yet · 1 started · 2 mostly · 3 clearly done (or "met" in the final report)
COMP_MAX, COMP_PASS = 5, 3  # evaluator: 1 not shown · 3 adequate · 5 excellent
STUCK_DAYS_DEFAULT, STUCK_DAYS_MAX = 7, 60
MANY_ATTEMPTS = 3
REASONS_SHOWN = 8
KEY_RE = re.compile(r"^[oc]\d{1,2}$")


def _int(v, hi):
    try:
        return max(0, min(hi, int(v)))
    except (TypeError, ValueError):
        return None


def concepts(sc) -> list[dict]:
    objs = [o for o in (sc.objectives or []) if isinstance(o, str)]
    comps = [c for c in (sc.competencies or []) if isinstance(c, dict)]
    return [
        {"key": f"o{i}", "kind": "objective", "name": o[:200], "max": OBJ_MAX, "pass": OBJ_PASS}
        for i, o in enumerate(objs)
    ] + [
        {
            "key": f"c{i}",
            "kind": "competency",
            "name": str(c.get("name", ""))[:80],
            "max": COMP_MAX,
            "pass": COMP_PASS,
        }
        for i, c in enumerate(comps)
    ]


def _comp_index(sc) -> dict:
    return {
        str(c.get("name", "")).casefold(): i
        for i, c in enumerate(sc.competencies or [])
        if isinstance(c, dict)
    }


def _coach_by_session(session_ids) -> dict[int, list[dict]]:
    from apps.roleplay.models import RolePlayTurn

    out = defaultdict(list)
    for sid, coach in (
        RolePlayTurn.objects.filter(session_id__in=session_ids, role="learner", coach__isnull=False)
        .order_by("created_at", "id")
        .values_list("session_id", "coach")
    ):
        if isinstance(coach, dict):
            out[sid].append(coach)
    return out


def _result(s) -> dict | None:
    return s.result if s.status == "completed" and isinstance(s.result, dict) else None


def levels(sc, sessions, coach) -> dict[str, int]:
    """Best level reached per concept key over all of one learner's attempts (missing key = no evidence yet)."""
    keys = {c["key"] for c in concepts(sc)}
    idx = _comp_index(sc)
    lv: dict[str, int] = {}

    def bump(key, v):
        if key in keys and v is not None and v > lv.get(key, -1):
            lv[key] = v

    for s in sessions:
        for c in coach.get(s.id, []):
            for i, o in enumerate(c.get("objectives") or []):
                if isinstance(o, dict):
                    bump(f"o{i}", _int(o.get("score"), OBJ_MAX))
        r = _result(s)
        if not r:
            continue
        for i, o in enumerate(r.get("objectives") or []):
            if isinstance(o, dict):
                bump(f"o{i}", OBJ_MAX if o.get("met") else 0)
        for k, c in enumerate(r.get("competencies") or []):
            if isinstance(c, dict):
                bump(f"c{idx.get(str(c.get('name', '')).casefold(), k)}", _int(c.get("score"), COMP_MAX))
    return lv


def _scores(sessions) -> list[int]:
    return [_int(r.get("overall"), 100) or 0 for s in sessions if (r := _result(s))]


def stuck_reasons(sessions, now, days: int) -> list[str]:
    """Why a learner looks stuck: stalled (started ≥ N days ago, nothing finished), many_attempts (≥3 finished without
    passing), no_improvement (later attempts never beat the first). `sessions` oldest first."""
    if not sessions:
        return []
    scores = _scores(sessions)
    passed = any(x >= PASS_SCORE for x in scores)
    out = []
    if not scores and now - sessions[0].started_at >= timedelta(days=days):
        out.append("stalled")
    if not passed and len(scores) >= MANY_ATTEMPTS:
        out.append("many_attempts")
    if not passed and len(scores) >= 2 and max(scores[1:]) <= scores[0]:
        out.append("no_improvement")
    return out


def _by_user(a, learners):
    from .teach import _sessions

    by_user = defaultdict(list)
    sessions = list(_sessions(a, [m.user_id for m in learners]))
    for s in sessions:
        by_user[s.user_id].append(s)
    return by_user, _coach_by_session([s.id for s in sessions])


def build(a, learners, now, days: int = STUCK_DAYS_DEFAULT) -> dict:
    """Everything the competency panel and the export need, over the viewer's learners."""
    from .teach import _name

    sc = a.scenario
    cs = concepts(sc)
    by_user, coach = _by_user(a, learners)
    rows, stuck = [], []
    funnel = Counter()
    for m in learners:
        ss = by_user[m.user_id]
        lv = levels(sc, ss, coach)
        scores = _scores(ss)
        passed = any(x >= PASS_SCORE for x in scores)
        funnel["assigned"] += 1
        funnel["started"] += bool(ss)
        funnel["completed"] += bool(scores)
        funnel["passed"] += passed
        cells = {
            c["key"]: {"level": lv.get(c["key"]), "passed": lv.get(c["key"], -1) >= c["pass"]} for c in cs
        }
        reasons = stuck_reasons(ss, now, days)
        row = {"user_id": m.user_id, "name": _name(m), "cells": cells, "passed": passed, "flags": reasons}
        rows.append(row)
        if reasons:
            last = ss[-1].started_at
            stuck.append(
                {
                    "user_id": m.user_id,
                    "name": row["name"],
                    "reasons": reasons,
                    "attempts": len(scores),
                    "best": max(scores) if scores else None,
                    "scores": scores[-6:],
                    "last_attempt": last,
                    "days_since": (now - last).days,
                }
            )
    n = len(learners)
    for c in cs:
        tried = sum(1 for r in rows if r["cells"][c["key"]]["level"] is not None)
        ok = sum(1 for r in rows if r["cells"][c["key"]]["passed"])
        c.update(
            attempted=tried,
            passed=ok,
            rate=round(ok / tried, 3) if tried else None,
            of_all=round(ok / n, 3) if n else None,
        )
    stages = ("assigned", "started", "completed", "passed")
    return {
        "concepts": cs,
        "matrix": rows,
        "pass_score": PASS_SCORE,
        "stuck_days": days,
        "funnel": [
            {"stage": k, "count": funnel[k], "pct": round(funnel[k] / n, 3) if n else None} for k in stages
        ],
        "stuck": sorted(stuck, key=lambda x: (-len(x["reasons"]), x["last_attempt"])),
    }


def level_text(cell, c) -> str:
    """Accessible / export text for one matrix cell: "3/3 ✓", "1/3", "—"."""
    if cell["level"] is None:
        return "—"
    return f"{cell['level']}/{c['max']}" + (" ✓" if cell["passed"] else "")


# ── Per-concept drill-down ───────────────────────────────────────────


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", s).split()).strip().rstrip(".").casefold()


class _Tally:
    def __init__(self):
        self.text, self.count, self.users = {}, Counter(), defaultdict(set)

    def add(self, text, uid):
        text = " ".join(str(text or "").split())[:200]
        k = _norm(text)
        if len(k) < 3 or uid in self.users[k]:
            return
        self.text.setdefault(k, text)
        self.count[k] += 1
        self.users[k].add(uid)

    def top(self):
        return [
            {"text": self.text[k], "learners": len(self.users[k])}
            for k, _ in self.count.most_common(REASONS_SHOWN)
        ]


def drill(a, learners, key) -> dict | None:
    """What learners got right / wrong for one concept: coach reasons per turn + the final evaluator's verdicts.
    Anonymous aggregates (learner counts), plus each learner's level for the teacher's own follow-up."""
    from .teach import _name

    sc = a.scenario
    c = next((x for x in concepts(sc) if x["key"] == key), None)
    if not c:
        return None
    i = int(key[1:])
    by_user, coach = _by_user(a, learners)
    idx = _comp_index(sc)
    right, wrong = _Tally(), _Tally()
    met = not_met = 0
    out_learners = []
    for m in learners:
        ss = by_user[m.user_id]
        for s in ss:
            for turn in coach.get(s.id, []):
                items = turn.get("objectives" if c["kind"] == "objective" else "competencies") or []
                if i < len(items) and isinstance(items[i], dict) and items[i].get("reason"):
                    score = _int(items[i].get("score"), OBJ_MAX) or 0
                    (right if score >= 2 else wrong).add(items[i]["reason"], m.user_id)
            r = _result(s)
            if not r:
                continue
            if c["kind"] == "objective":
                objs = r.get("objectives") or []
                if i < len(objs) and isinstance(objs[i], dict):
                    met, not_met = met + bool(objs[i].get("met")), not_met + (not objs[i].get("met"))
            else:
                for k, comp in enumerate(r.get("competencies") or []):
                    if (
                        isinstance(comp, dict)
                        and idx.get(str(comp.get("name", "")).casefold(), k) == i
                        and comp.get("comment")
                    ):
                        score = _int(comp.get("score"), COMP_MAX) or 0
                        (right if score >= COMP_PASS else wrong).add(comp["comment"], m.user_id)
        lv = levels(sc, ss, coach).get(key)
        out_learners.append(
            {
                "user_id": m.user_id,
                "name": _name(m),
                "level": lv,
                "passed": lv is not None and lv >= c["pass"],
                "attempts": len(_scores(ss)),
            }
        )
    tried = [x for x in out_learners if x["level"] is not None]
    return {
        "concept": {
            **c,
            "attempted": len(tried),
            "passed": sum(x["passed"] for x in tried),
            "rate": round(sum(x["passed"] for x in tried) / len(tried), 3) if tried else None,
        },
        "right": right.top(),
        "wrong": wrong.top(),
        "final": {"met": met, "not_met": not_met} if c["kind"] == "objective" else None,
        "learners": out_learners,
    }


def _n(n, word) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def drill_prompt(sc, d) -> str:
    c = d["concept"]
    lines = [
        f"Scenario: {sc.title}",
        f"Learner's role: {sc.learner_role}",
        f"Concept ({c['kind']}): {c['name']}",
        f"Learners who tried: {c['attempted']}, reached it: {c['passed']}",
    ]
    if d["final"]:
        lines.append(
            f"Final reports: met {_n(d['final']['met'], 'time')}, not met {_n(d['final']['not_met'], 'time')}"
        )
    notes = [f"GOT RIGHT ({_n(x['learners'], 'learner')}): {x['text']}" for x in d["right"]]
    notes += [f"GOT WRONG ({_n(x['learners'], 'learner')}): {x['text']}" for x in d["wrong"]]
    lines.append(fence("coach_notes", "\n".join(notes)))  # learner text can't close the fence
    return "\n".join(lines)[:8000]


# ── Export ───────────────────────────────────────────────────────────


def export_tables(data) -> list[tuple[str, list[str], list[list]]]:
    """Extra sheets: concept matrix (text cells + a pass-rate row), funnel, stuck learners. Names / concept text are
    learner- or author-written: callers write them formula-safe (CSV) or as text cells (XLSX)."""
    cs = data["concepts"]
    matrix = [
        [
            r["name"],
            *(level_text(r["cells"][c["key"]], c) for c in cs),
            "yes" if r["passed"] else "no",
            ", ".join(r["flags"]),
        ]
        for r in data["matrix"]
    ]
    matrix.append(
        [
            "Pass rate (of learners who tried)",
            *(
                f"{round(c['rate'] * 100)}% ({c['passed']}/{c['attempted']})"
                if c["rate"] is not None
                else "—"
                for c in cs
            ),
            "",
            "",
        ]
    )
    funnel = [
        [f["stage"], f["count"], f"{round(f['pct'] * 100)}%" if f["pct"] is not None else "—"]
        for f in data["funnel"]
    ]
    stuck = [
        [
            s["name"],
            ", ".join(s["reasons"]),
            s["attempts"],
            s["best"],
            s["days_since"],
            s["last_attempt"].strftime("%Y-%m-%d"),
        ]
        for s in data["stuck"]
    ]
    return [
        (
            "Concepts",
            [
                "Learner",
                *(f"{'Objective' if c['kind'] == 'objective' else 'Competency'}: {c['name']}" for c in cs),
                "Passed",
                "Flags",
            ],
            matrix,
        ),
        ("Funnel", ["Stage", "Learners", "% of assigned"], funnel),
        (
            "Stuck learners",
            ["Learner", "Reasons", "Attempts", "Best score", "Days since last attempt", "Last attempt"],
            stuck,
        ),
    ]
