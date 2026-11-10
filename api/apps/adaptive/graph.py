"""A course's concept graph: which concepts each lesson teaches and which concepts depend on which.

Built by AI when an outline is generated (the author's generation pays for it). Courses that existed before, or whose
AI graph failed, get a plain graph — one concept per lesson, no extra dependencies — built without AI, so a learner
opening a shared course never triggers paid generation. Lessons added later (Studio edits) are covered the same way."""

import logging

from django.db import transaction
from django.utils.text import slugify

from apps.learning.models import Activity, Curriculum, Subsection

from .models import ActivityConcept, Concept, ConceptEdge, ConceptLink

log = logging.getLogger(__name__)
MAX_CONCEPTS = 30


def _lessons(cur) -> list[Subsection]:
    return list(
        Subsection.objects.filter(section__curriculum=cur, archived=False, section__archived=False).order_by(
            "section__order", "order"
        )
    )


def _ai_graph(cur, lessons):
    from llm.prompts.adaptive import GRAPH_SYSTEM, ConceptGraph
    from llm.prompts.curriculum import LANG_RULE
    from llm.structured import complete_json_sync

    outline = "\n".join(f"L{i + 1}. {s.title}: {s.objective}" for i, s in enumerate(lessons))
    goal = getattr(cur, "learning_goal", None)
    target = (goal.scenario.get("deliverable") if goal else "") or cur.goal
    return complete_json_sync(
        "adaptive_graph",
        GRAPH_SYSTEM.format(lang_rule=LANG_RULE.get(cur.language, LANG_RULE["en"])),
        f"Course: {cur.title or cur.goal}\nGoal: {target}\n\nLessons:\n{outline[:8000]}",
        ConceptGraph,
        max_tokens=4000,
    )


def _acyclic(edges: set[tuple[str, str]]) -> set[tuple[str, str]]:
    """Drop edges that close a cycle, keeping earlier-added ones (edges are (prereq, concept))."""
    kept: set[tuple[str, str]] = set()
    after: dict[str, set[str]] = {}

    def reaches(a, b, seen=None):
        seen = seen or set()
        if a == b:
            return True
        seen.add(a)
        return any(reaches(n, b, seen) for n in after.get(a, ()) if n not in seen)

    for p, c in sorted(edges):
        if reaches(c, p):  # c already leads to p: p → c would make a cycle
            log.info("concept graph: dropped cyclic edge %s -> %s", p, c)
            continue
        kept.add((p, c))
        after.setdefault(p, set()).add(c)
    return kept


def _save_ai(cur, lessons, graph) -> None:
    keymap: dict[str, str] = {}
    specs = []
    for g in graph.concepts[:MAX_CONCEPTS]:
        key = slugify(g.key)[:60] or slugify(g.title)[:60]
        if not key or key in keymap.values():
            continue
        keymap[g.key] = key
        specs.append((key, g))
    links: dict[int, list[str]] = {}
    for gl in graph.lessons:
        if 1 <= gl.lesson <= len(lessons):
            keys = [keymap[k] for k in gl.concepts if k in keymap]
            links.setdefault(lessons[gl.lesson - 1].id, [])
            for k in keys:
                if k not in links[lessons[gl.lesson - 1].id]:
                    links[lessons[gl.lesson - 1].id].append(k)
    taught = {k for ks in links.values() for k in ks}
    specs = [(k, g) for k, g in specs if k in taught]  # a concept no lesson teaches can't be learned here
    keys = {k for k, _ in specs}
    edges = {
        (keymap[p], k)
        for k, g in specs
        for p in g.prereqs
        if p in keymap and keymap[p] in keys and keymap[p] != k
    }
    concepts = {
        k: Concept.objects.create(
            curriculum=cur,
            key=k,
            title=g.title[:160],
            description=g.description[:300],
            order=i,
            critical=g.critical,
        )
        for i, (k, g) in enumerate(specs)
    }
    for p, c in _acyclic(edges):
        ConceptEdge.objects.create(prereq=concepts[p], concept=concepts[c])
    for sub_id, ks in links.items():
        for i, k in enumerate(k for k in ks if k in concepts):
            if i < 3:
                ConceptLink.objects.create(subsection_id=sub_id, concept=concepts[k], order=i)


def _cover_lessons(cur, lessons) -> None:
    """Every lesson teaches at least one concept: give uncovered lessons their own."""
    covered = set(ConceptLink.objects.filter(subsection__in=lessons).values_list("subsection_id", flat=True))
    start = Concept.objects.filter(curriculum=cur).count()
    for i, s in enumerate(x for x in lessons if x.id not in covered):
        c, _ = Concept.objects.get_or_create(
            curriculum=cur,
            key=f"lesson-{s.id}",
            defaults={"title": s.title[:160], "description": s.objective[:300], "order": start + i},
        )
        ConceptLink.objects.get_or_create(subsection=s, concept=c)


def build(cur: Curriculum, *, use_ai: bool) -> None:
    """(Re)build the graph from scratch. Mastery on the old concepts goes with them (the outline was regenerated)."""
    lessons = _lessons(cur)
    graph = None
    if use_ai and lessons:
        try:
            graph = _ai_graph(cur, lessons)
        except Exception:
            log.warning(
                "concept graph failed for course %s; using one concept per lesson", cur.id, exc_info=True
            )
    with transaction.atomic():
        Concept.objects.filter(curriculum=cur).delete()
        if graph:
            _save_ai(cur, lessons, graph)
        _cover_lessons(cur, lessons)
    _replan_all(cur)


def _replan_all(cur) -> None:
    """Paths made before this (re)build point at concepts that no longer exist: re-plan them on the new graph."""
    from .models import LearnerPath
    from .services import replan

    for path in LearnerPath.objects.filter(curriculum=cur):
        try:
            replan(path)
        except Exception:
            log.exception("re-plan after graph rebuild failed for path %s", path.id)


def ensure(cur: Curriculum) -> None:
    """A graph exists and covers every live lesson. No AI."""
    lessons = _lessons(cur)
    if not lessons:
        return
    with transaction.atomic():
        Curriculum.objects.select_for_update().filter(pk=cur.pk).first()  # one builder at a time per course
        _cover_lessons(cur, lessons)


def tag_activities(sub: Subsection, hints: dict[int, str] | None = None) -> None:
    """Tag each of the lesson's untagged activities with one of its concepts: the model's hint (a concept key) when it
    names one of this lesson's concepts, else the lesson's main concept."""
    links = list(ConceptLink.objects.filter(subsection=sub).select_related("concept"))
    if not links:
        return
    by_key = {lk.concept.key: lk.concept for lk in links}
    main = links[0].concept
    tagged = set(
        ActivityConcept.objects.filter(activity__subsection=sub).values_list("activity_id", flat=True)
    )
    for a in Activity.objects.filter(subsection=sub).exclude(id__in=tagged):
        hint = slugify((hints or {}).get(a.order, ""))
        ActivityConcept.objects.get_or_create(activity=a, defaults={"concept": by_key.get(hint, main)})
