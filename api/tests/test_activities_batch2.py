import json

import pytest

from apps.learning import activities as acts
from apps.learning.safe_math import valid_expression
from apps.learning.services import _tree_ok, _valid

TREE = [
    {
        "id": "start",
        "text": "A customer is angry about a late delivery.",
        "choices": [
            {"text": "Apologise and check the order", "next": "check", "ending_score": 0, "feedback": ""},
            {
                "text": "Blame the courier",
                "next": "",
                "ending_score": 0.1,
                "feedback": "Blaming others loses trust.",
            },
        ],
    },
    {
        "id": "check",
        "text": "The order was stuck at the hub.",
        "choices": [
            {
                "text": "Offer a refund and a new ETA",
                "next": "",
                "ending_score": 1.0,
                "feedback": "Clear and caring!",
            },
            {
                "text": "Say nothing",
                "next": "",
                "ending_score": 0.3,
                "feedback": "Silence frustrates customers.",
            },
        ],
    },
]


class FakeActivity:
    def __init__(self, t, payload, key):
        self.type, self.payload, self.key = t, payload, key


def make(act):
    payload, key = acts.build(act, seed=7)
    return FakeActivity(act["type"], payload, key), payload, key


def test_decision_tree_grading_and_hidden_scores():
    a, payload, _ = make(
        {"type": "decision_tree", "title": "t", "prompt": "p", "tree": TREE, "explanation": "e"}
    )
    blob = json.dumps(payload)
    assert "ending_score" not in blob and "feedback" not in blob and "1.0" not in blob
    assert acts.grade(a, {"path": ["start.0", "check.0"]}, "en").score == 1.0
    mid = acts.grade(a, {"path": ["start.0", "check.1"]}, "en")
    assert mid.score == pytest.approx(0.3) and "Silence" in mid.feedback
    assert acts.grade(a, {"path": ["start.1"]}, "en").score == pytest.approx(0.1)
    assert acts.grade(a, {"path": ["check.0"]}, "en").score == 0.0  # can't skip the start
    assert acts.grade(a, {"path": ["start.1", "check.0"]}, "en").score == 0.0  # continuing after an ending
    assert acts.grade(a, {"path": ["start.0"]}, "en").score == 0.0  # unfinished


def test_tree_validation():
    assert _tree_ok(TREE)
    loop = [
        {"id": "a", "text": "x", "choices": [{"text": "1", "next": "b"}, {"text": "2", "next": ""}]},
        {"id": "b", "text": "y", "choices": [{"text": "1", "next": "a"}, {"text": "2", "next": ""}]},
    ]
    assert not _tree_ok(loop)
    dangling = [
        {"id": "a", "text": "x", "choices": [{"text": "1", "next": "zzz"}, {"text": "2", "next": ""}]}
    ]
    assert not _tree_ok(dangling)


def test_concept_map_partial_credit_and_hidden_labels():
    links = [
        {"source": "Data", "target": "Model", "label": "trains"},
        {"source": "Model", "target": "Prediction", "label": "produces"},
    ]
    a, payload, _ = make(
        {"type": "concept_map", "title": "t", "prompt": "p", "links": links, "explanation": "e"}
    )
    assert sorted(payload["labels"]) == ["produces", "trains"] and "label" not in json.dumps(payload["links"])
    assert acts.grade(a, {"labels": {"k0": "trains", "k1": "produces"}}, "en").score == 1.0
    assert acts.grade(a, {"labels": {"k0": "trains", "k1": "trains"}}, "en").score == 0.5


def test_viz_and_slides_are_choice_graded():
    viz = {
        "type": "viz",
        "title": "t",
        "prompt": "p",
        "options": ["up", "down"],
        "correct": [0],
        "explanation": "e",
        "viz": {
            "kind": "function_plot",
            "expression": "a*x + b",
            "x_min": 0,
            "x_max": 10,
            "sides": 2,
            "params": [
                {"name": "a", "min": -5, "max": 5, "step": 0.5, "value": 1},
                {"name": "b", "min": 0, "max": 10, "step": 1, "value": 0},
            ],
        },
    }
    a, payload, _ = make(viz)
    assert "correct" not in json.dumps(payload) and _valid(viz)
    assert acts.grade(a, {"selected": [0]}, "en").correct
    slides = {
        "type": "slides",
        "title": "t",
        "prompt": "p",
        "slides": [{"title": "1", "text": "a"}, {"title": "2", "text": "b"}],
        "options": ["x", "y"],
        "correct": [1],
        "explanation": "e",
    }
    s, _, _ = make(slides)
    assert acts.grade(s, {"selected": [1]}, "en").score == 1.0


def test_safe_math_whitelist():
    ok = {"x", "a", "b"}
    assert valid_expression("a*x^2 + sin(x) - sqrt(b)", ok)
    for bad in (
        "__import__('os')",
        "x.__class__",
        "open(x)",
        "[x for x in a]",
        "lambda: 1",
        "'a'*3",
        "y + 1",
        "sin(x, x)",
    ):
        assert not valid_expression(bad, ok), bad


def test_task_link_allowlist():
    _, payload, key = make(
        {
            "type": "task",
            "title": "t",
            "prompt": "p",
            "steps": ["Open the tool"],
            "rubric": ["shows output"],
            "model_answer": "m",
            "link": "https://evil.example.com/phish",
        }
    )
    assert payload["link"] == "" and "model_answer" not in json.dumps(payload)
    _, payload2, _ = make(
        {
            "type": "task",
            "title": "t",
            "prompt": "p",
            "steps": ["s"],
            "rubric": ["r"],
            "model_answer": "m",
            "link": "https://claude.ai",
        }
    )
    assert payload2["link"] == "https://claude.ai"


def test_flat_extra_json_round_trip():
    import json as _json

    from llm.prompts.curriculum import FlatActivity, to_typed

    tree = to_typed(
        FlatActivity(
            type="decision_tree", title="t", prompt="p", explanation="e", extra=_json.dumps({"tree": TREE})
        )
    )
    assert tree and tree["tree"][0]["id"] == "start"
    task = to_typed(
        FlatActivity(
            type="task",
            title="t",
            prompt="p",
            rubric=["r"],
            model_answer="m",
            extra='{"steps": ["a"], "link": ""}',
        )
    )
    assert task and task["steps"] == ["a"]
    assert (
        to_typed(FlatActivity(type="concept_map", title="t", prompt="p", explanation="e", extra="not json"))
        is None
    )
    assert (
        to_typed(
            FlatActivity(
                type="slides",
                title="t",
                prompt="p",
                options=["a", "b"],
                correct=[0],
                explanation="e",
                extra="{}",
            )
        )
        is None
    )


def test_best_snippet_picks_relevant_sentence():
    from apps.docs.search import best_snippet

    chunk = "Rewards guide agents. Overfitting is memorising noise in training data. Splits are 70/15/15."
    assert best_snippet(chunk, "what is overfitting memorising").startswith("Overfitting is memorising")
