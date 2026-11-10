"""Readable, plain-text views of a learner's answer and of the answer key, per activity type (teacher drill-down only).

Never imported by learner-facing code: `render_key` exposes the key, so callers must have checked the teacher's role."""

LETTERS = "ABCDEFGHIJKLMNOP"
CAP = 600  # long answers are cut for tables; teachers see the gist


def _cut(s, n=CAP) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _opt(options, i) -> str:
    try:
        i = int(i)
        return f"{LETTERS[i] if i < len(LETTERS) else i + 1}) {options[i]}"
    except (ValueError, TypeError, IndexError):
        return "?"


def _by_id(items) -> dict:
    return {x.get("id"): x.get("text", x.get("label", "")) for x in items or [] if isinstance(x, dict)}


def _choices(payload, picked) -> str:
    return "; ".join(_opt(payload.get("options", []), i) for i in picked or []) or "—"


def render_answer(activity, answer) -> str:
    t, p, a = activity.type, activity.payload or {}, answer if isinstance(answer, dict) else {}
    if t in ("quiz", "diagram", "slides", "viz"):
        return _choices(p, a.get("selected"))
    if t == "fill_blank":
        return " · ".join(f"[{k}] {_cut(v, 80)}" for k, v in (a.get("blanks") or {}).items()) or "—"
    if t == "sequencing":
        items = _by_id(p.get("items"))
        return " → ".join(_cut(items.get(i, "?"), 60) for i in a.get("order") or []) or "—"
    if t == "categorization":
        items = _by_id(p.get("items"))
        return (
            "; ".join(
                f"{_cut(items.get(i, '?'), 50)} → {_cut(c, 40)}" for i, c in (a.get("assign") or {}).items()
            )
            or "—"
        )
    if t == "matching":
        left, right = _by_id(p.get("left")), _by_id(p.get("right"))
        return (
            "; ".join(
                f"{_cut(left.get(l, '?'), 50)} ↔ {_cut(right.get(r, '?'), 50)}"
                for l, r in (a.get("pairs") or {}).items()
            )
            or "—"
        )
    if t == "concept_map":
        links = {x["id"]: x for x in p.get("links", []) if isinstance(x, dict)}
        return (
            "; ".join(
                f"{links.get(k, {}).get('source', '?')} —{_cut(v, 40)}→ {links.get(k, {}).get('target', '?')}"
                for k, v in (a.get("labels") or {}).items()
            )
            or "—"
        )
    if t == "decision_tree":
        texts = {c["id"]: c["text"] for n in (p.get("nodes") or {}).values() for c in n.get("choices", [])}
        return " → ".join(_cut(texts.get(c, "?"), 60) for c in a.get("path") or []) or "—"
    if t in ("task", "open_input"):
        return _cut(a.get("text")) or "—"
    if t == "browser_task":
        return _cut(a.get("text")) or "(screenshot)"
    if t == "code":
        return _cut(a.get("code")) or "—"
    if t == "map":
        names = {x["id"]: x["name"] for x in p.get("targets", []) if isinstance(x, dict)}
        pts = a.get("points") or {}
        return (
            "; ".join(
                f"{names.get(k, k)}: {v.get('lat', '?')}, {v.get('lon', '?')}"
                for k, v in pts.items()
                if isinstance(v, dict)
            )
            or "—"
        )
    if t == "hotspot":
        labels = _by_id(p.get("labels"))
        pts = a.get("points") or {}
        return (
            "; ".join(
                f"{labels.get(k, k)}: ({v.get('x', '?')}, {v.get('y', '?')})"
                for k, v in pts.items()
                if isinstance(v, dict)
            )
            or "—"
        )
    if t == "video":
        cps = {c["id"]: c for c in p.get("checkpoints", []) if isinstance(c, dict)}
        return (
            " · ".join(
                f"{_cut(cps.get(k, {}).get('question', k), 50)}: {_choices(cps.get(k, {}), v)}"
                for k, v in (a.get("answers") or {}).items()
            )
            or "—"
        )
    if t == "roleplay":
        return "(role-play conversation)"
    return _cut(a)


def render_key(activity) -> dict:
    """{"answer": readable correct answer, "rationale": explanation / rubric}."""
    t, p, k = activity.type, activity.payload or {}, activity.key or {}
    why = k.get("explanation", "")
    if t in ("quiz", "diagram", "slides", "viz"):
        return {"answer": _choices(p, k.get("correct")), "rationale": why}
    if t == "fill_blank":
        return {
            "answer": " · ".join(f"[{b}] {' / '.join(v[:3])}" for b, v in (k.get("blanks") or {}).items()),
            "rationale": why,
        }
    if t == "sequencing":
        items = _by_id(p.get("items"))
        return {
            "answer": " → ".join(_cut(items.get(i, "?"), 60) for i in k.get("order", [])),
            "rationale": why,
        }
    if t == "categorization":
        items = _by_id(p.get("items"))
        return {
            "answer": "; ".join(
                f"{_cut(items.get(i, '?'), 50)} → {c}" for i, c in (k.get("assign") or {}).items()
            ),
            "rationale": why,
        }
    if t == "matching":
        left, right = _by_id(p.get("left")), _by_id(p.get("right"))
        return {
            "answer": "; ".join(
                f"{left.get(l, '?')} ↔ {right.get(r, '?')}" for l, r in (k.get("pairs") or {}).items()
            ),
            "rationale": why,
        }
    if t == "concept_map":
        links = {x["id"]: x for x in p.get("links", []) if isinstance(x, dict)}
        return {
            "answer": "; ".join(
                f"{links.get(i, {}).get('source', '?')} —{v}→ {links.get(i, {}).get('target', '?')}"
                for i, v in (k.get("labels") or {}).items()
            ),
            "rationale": why,
        }
    if t == "decision_tree":
        texts = {c["id"]: c["text"] for n in (p.get("nodes") or {}).values() for c in n.get("choices", [])}
        ends = k.get("endings") or {}
        best = max((e["score"] for e in ends.values()), default=0)
        good = [
            f"{_cut(texts.get(c, c), 80)} ({e['feedback'][:120]})"
            for c, e in ends.items()
            if e["score"] == best
        ]
        return {"answer": "; ".join(good), "rationale": why}
    if t in ("task", "open_input", "browser_task"):
        return {"answer": _cut(k.get("model_answer")), "rationale": "; ".join(k.get("rubric", []))}
    if t == "code":
        return {"answer": _cut(k.get("model_solution")), "rationale": "; ".join(k.get("rubric", []))}
    if t == "map":
        return {
            "answer": "; ".join(
                f"{v['name']}: {v['lat']}, {v['lon']}" for v in (k.get("places") or {}).values()
            ),
            "rationale": f"Within {k.get('tolerance_km', '?')} km. {why}".strip(),
        }
    if t == "hotspot":
        labels = _by_id(p.get("labels"))
        return {
            "answer": "; ".join(
                f"{labels.get(i, i)}: ({v['x']}, {v['y']})" for i, v in (k.get("targets") or {}).items()
            ),
            "rationale": why,
        }
    if t == "video":
        cps = {c["id"]: c for c in p.get("checkpoints", []) if isinstance(c, dict)}
        return {
            "answer": " · ".join(
                f"{_cut(cps.get(c, {}).get('question', c), 50)}: {_choices(cps.get(c, {}), v)}"
                for c, v in (k.get("correct") or {}).items()
            ),
            "rationale": why,
        }
    if t == "roleplay":
        sc = k.get("scenario") or {}
        return {"answer": "; ".join(sc.get("objectives", [])), "rationale": sc.get("goal", "")}
    return {"answer": "", "rationale": why}
