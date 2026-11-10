"""The adaptive path planner is pure: these tests need no database."""

from apps.adaptive.planner import (
    KNOWN,
    MASTERED,
    PRIOR,
    WEAK,
    Item,
    Learner,
    Lesson,
    Mastery,
    changes,
    critical_mastered,
    order_lessons,
    plan,
)
from apps.review.scheduling import bkt_update, guess_for

QUIZ_GUESS = guess_for("quiz", 4)


def _run(*answers, p=PRIOR):
    for ok in answers:
        p = bkt_update(p, ok, QUIZ_GUESS)
    return p


def kinds(items):
    return [(i.kind, i.subsection_id) for i in items]


# ── thresholds vs the real BKT constants ─────────────────────────────


def test_three_correct_first_attempts_reach_mastered_and_known():
    assert _run(True, True) < KNOWN  # two lucky answers are not enough to skip anything
    assert _run(True, True, True) >= max(KNOWN, MASTERED)


def test_one_wrong_answer_after_known_counts_as_weak():
    assert _run(False, p=KNOWN) < WEAK


def test_mostly_wrong_lesson_is_weak_and_mostly_right_is_not():
    assert _run(False, False, True) < WEAK
    assert _run(True, False, True) >= WEAK


# ── ordering ─────────────────────────────────────────────────────────


def test_prerequisites_reorder_lessons_and_outline_breaks_ties():
    lessons = [Lesson(1, ("bots",)), Lesson(2, ("prompting",)), Lesson(3, ("excel",))]
    out = order_lessons(lessons, {"bots": {"prompting"}})
    assert [x.id for x in out] == [2, 1, 3]


def test_cycle_falls_back_to_outline_order():
    lessons = [Lesson(1, ("a",)), Lesson(2, ("b",)), Lesson(3, ("c",))]
    out = order_lessons(lessons, {"a": {"b"}, "b": {"a"}})
    assert [x.id for x in out] == [3, 1, 2] or [x.id for x in out][-2:] == [1, 2]
    assert sorted(x.id for x in out) == [1, 2, 3]


def test_prereq_taught_in_same_lesson_is_ignored():
    lessons = [Lesson(1, ("a", "b")), Lesson(2, ("c",))]
    assert [x.id for x in order_lessons(lessons, {"b": {"a"}})] == [1, 2]


# ── planning ─────────────────────────────────────────────────────────


def test_new_learner_gets_every_lesson_then_final():
    lessons = [Lesson(1, ("a",)), Lesson(2, ("b",))]
    assert kinds(plan(lessons, {}, Learner())) == [("lesson", 1), ("lesson", 2), ("final", None)]


def test_known_concepts_become_a_skip_check():
    learner = Learner(mastery={"excel": Mastery(0.9, 2)})
    lessons = [Lesson(1, ("prompting",)), Lesson(2, ("excel",))]
    items = plan(lessons, {}, learner)
    assert kinds(items) == [("lesson", 1), ("skip_check", 2), ("final", None)]
    assert items[1].reason == "known"


def test_skip_needs_every_concept_known_and_enough_evidence():
    lessons = [Lesson(1, ("a", "b"))]
    one_known = Learner(mastery={"a": Mastery(0.95, 4), "b": Mastery(0.3, 4)})
    thin = Learner(mastery={"a": Mastery(0.95, 1)})
    assert plan([Lesson(1, ("a",))], {}, thin)[0].kind == "lesson"
    assert plan(lessons, {}, one_known)[0].kind == "lesson"


def test_started_lesson_is_never_turned_into_a_skip():
    learner = Learner(mastery={"a": Mastery(0.95, 5)})
    assert plan([Lesson(1, ("a",), "in_progress")], {}, learner)[0].kind == "lesson"


def test_weak_concept_after_completion_adds_practice_once():
    lessons = [Lesson(1, ("a",), "completed"), Lesson(2, ("b",))]
    weak = Learner(mastery={"a": Mastery(0.3, 4)})
    assert kinds(plan(lessons, {}, weak)) == [
        ("lesson", 1),
        ("remediation", 1),
        ("lesson", 2),
        ("final", None),
    ]
    assert plan(lessons, {}, weak)[0].status == "done"
    weak.remediated.add(1)
    again = plan(lessons, {}, weak)
    assert [(i.kind, i.status) for i in again if i.subsection_id == 1] == [
        ("lesson", "done"),
        ("remediation", "done"),
    ]


def test_weak_needs_enough_evidence():
    lessons = [Lesson(1, ("a",), "completed")]
    assert ("remediation", 1) not in kinds(plan(lessons, {}, Learner(mastery={"a": Mastery(0.2, 2)})))


def test_refused_completion_puts_practice_before_the_retry():
    items = plan([Lesson(1, ("a",), "in_progress")], {}, Learner(refused={1}))
    assert kinds(items) == [("remediation", 1), ("lesson", 1), ("final", None)]
    assert items[0].reason == "retry"


def test_practised_retry_keeps_the_done_practice_and_reopens_the_lesson():
    items = plan([Lesson(1, ("a",), "in_progress")], {}, Learner(refused={1}, remediated={1}))
    assert [(i.kind, i.status) for i in items] == [
        ("remediation", "done"),
        ("lesson", "pending"),
        ("final", "pending"),
    ]


def test_final_done():
    assert plan([], {}, Learner(final_done=True))[-1] == Item("final", None, "", "done")


def test_changes_counts_only_what_moved():
    old = [Item("skip_check", 2), Item("lesson", 3)]
    new = [Item("lesson", 2), Item("remediation", 1), Item("lesson", 3), Item("skip_check", 4)]
    assert changes(old, new) == {"practice": 1, "skip": 1, "unskip": 1}
    done_skip = [Item("lesson", 2, status="done")]
    assert changes(old, done_skip)["unskip"] == 0  # a passed skip-check is not an "unskip"


def test_critical_mastered():
    learner = Learner(mastery={"a": Mastery(0.9, 4), "b": Mastery(0.7, 4)})
    assert critical_mastered(["a"], learner)
    assert not critical_mastered(["a", "b"], learner)
    assert not critical_mastered(["c"], learner)
