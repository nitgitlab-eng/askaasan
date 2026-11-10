"""The path planner: pure functions, no database, no AI.

Given the syllabus (lessons in outline order and the concepts each teaches), the concept prerequisites and one learner's
mastery, decide that learner's path:

- lessons come in prerequisite order (outline order breaks ties, and wins if the graph has a cycle);
- a lesson whose every concept the learner already seems to know becomes a quick skip-check (fast-track) instead;
- a completed lesson whose concept is still weak gets a practice step right after it (once);
- a lesson whose completion was refused (score below the pass mark) gets a practice step before it is retried;
- one final check closes the path.

Thresholds are tuned to `apps.review.scheduling.bkt_update` (P_LEARN 0.15, P_SLIP 0.1, prior 0.2): about three correct
first attempts take a concept from 0.2 to ≥ 0.9, and a single wrong answer at 0.85 drops it to about 0.52. See
tests/test_adaptive_planner.py."""

import heapq
from dataclasses import dataclass, field

KNOWN = 0.85  # offer a skip-check at or above this
OFFER_OBS = 2  # ...after at least this many observations (a correct pre-test answer counts as two)
WEAK = 0.6  # practice below this
MIN_OBS = 3  # ...but only with enough evidence (a lesson has 3-5 activities)
REMEDIATED = 0.7  # a practice step is done once the concept is back above this (above WEAK: no flapping)
MASTERED = 0.8  # certificate: every critical concept at or above this
PRIOR = 0.2


@dataclass(frozen=True)
class Lesson:
    id: int
    concepts: tuple[str, ...]
    state: str = "not_started"  # not_started | in_progress | completed


@dataclass(frozen=True)
class Mastery:
    p: float = PRIOR
    obs: int = 0


@dataclass(frozen=True)
class Item:
    kind: str  # lesson | skip_check | remediation | final
    subsection_id: int | None
    concept: str = ""
    status: str = "pending"  # pending | done
    reason: str = ""  # code for the learner-facing text: known | weak | retry | ""


@dataclass
class Learner:
    mastery: dict[str, Mastery] = field(default_factory=dict)
    refused: set[int] = field(
        default_factory=set
    )  # lessons whose completion was refused, practice not done yet
    remediated: set[int] = field(default_factory=set)  # lessons that already had a practice step done
    final_done: bool = False

    def m(self, key: str) -> Mastery:
        return self.mastery.get(key, Mastery())


def is_known(m: Mastery) -> bool:
    return m.p >= KNOWN and m.obs >= OFFER_OBS


def is_weak(m: Mastery) -> bool:
    return m.p < WEAK and m.obs >= MIN_OBS


def order_lessons(lessons: list[Lesson], prereqs: dict[str, set[str]]) -> list[Lesson]:
    """Stable topological order: a lesson comes after the lessons that first teach its concepts' prerequisites.
    Outline position breaks ties; anything left in a cycle keeps outline order."""
    pos = {les.id: i for i, les in enumerate(lessons)}
    teacher: dict[str, int] = {}
    for les in lessons:
        for c in les.concepts:
            teacher.setdefault(c, les.id)
    deps: dict[int, set[int]] = {les.id: set() for les in lessons}
    for les in lessons:
        for c in les.concepts:
            for p in prereqs.get(c, ()):
                t = teacher.get(p)
                if t is not None and t != les.id:
                    deps[les.id].add(t)
    indeg = {i: len(d) for i, d in deps.items()}
    users: dict[int, list[int]] = {i: [] for i in deps}
    for i, d in deps.items():
        for t in d:
            users[t].append(i)
    ready = [(pos[i], i) for i, n in indeg.items() if n == 0]
    heapq.heapify(ready)
    out: list[int] = []
    while ready:
        _, i = heapq.heappop(ready)
        out.append(i)
        for u in users[i]:
            indeg[u] -= 1
            if indeg[u] == 0:
                heapq.heappush(ready, (pos[u], u))
    left = sorted((i for i in deps if i not in set(out)), key=pos.get)  # a cycle: fall back to outline order
    by_id = {les.id: les for les in lessons}
    return [by_id[i] for i in out + left]


def plan(lessons: list[Lesson], prereqs: dict[str, set[str]], learner: Learner) -> list[Item]:
    items: list[Item] = []
    for les in order_lessons(lessons, prereqs):
        ms = [learner.m(c) for c in les.concepts]
        weakest = min(les.concepts, key=lambda c: learner.m(c).p) if les.concepts else ""
        if les.state == "completed":
            items.append(Item("lesson", les.id, weakest, "done"))
            if les.id in learner.remediated:
                items.append(Item("remediation", les.id, weakest, "done"))
            elif any(is_weak(m) for m in ms):
                items.append(Item("remediation", les.id, weakest, reason="weak"))
            continue
        if les.id in learner.remediated:  # practised after a refused finish: the retry is open now
            items.append(Item("remediation", les.id, weakest, "done", "retry"))
            items.append(Item("lesson", les.id, weakest))
            continue
        if les.id in learner.refused:
            items.append(Item("remediation", les.id, weakest, reason="retry"))
            items.append(Item("lesson", les.id, weakest))
            continue
        if les.state == "not_started" and ms and all(is_known(m) for m in ms):
            items.append(Item("skip_check", les.id, weakest, reason="known"))
            continue
        items.append(Item("lesson", les.id, weakest))
    items.append(Item("final", None, "", "done" if learner.final_done else "pending"))
    return items


def changes(old: list[Item], new: list[Item]) -> dict[str, int]:
    """What a re-plan changed in the pending part of the path, for the "your path was updated" note."""

    def pending(items, kind):
        return {i.subsection_id for i in items if i.kind == kind and i.status == "pending"}

    old_skip, new_skip = pending(old, "skip_check"), pending(new, "skip_check")
    return {
        "practice": len(pending(new, "remediation") - pending(old, "remediation")),
        "skip": len(new_skip - old_skip),
        # a lesson that was offered as a skip-check is a full lesson again (mastery dropped)
        "unskip": len(old_skip & pending(new, "lesson")),
    }


def critical_mastered(critical: list[str], learner: Learner) -> bool:
    return all(learner.m(c).p >= MASTERED for c in critical)
