import json

import pytest

from apps.accounts.models import User
from apps.learning.models import Activity

pytestmark = pytest.mark.django_db


@pytest.fixture
def course(auth):
    client, _ = auth
    res = client.post(
        "/api/learn/curriculums/", {"goal": "Understand AI basics", "level": "beginner"}, format="json"
    )
    assert res.status_code == 202
    return client, res.data["id"]


def _lesson(client, cid):
    detail = client.get(f"/api/learn/curriculums/{cid}/").data
    sub_id = detail["sections"][0]["subsections"][0]["id"]
    return client.post(f"/api/learn/subsections/{sub_id}/start/").data


def _act(lesson, t):
    return next(a for a in lesson["activities"] if a["type"] == t)


def test_outline_generated(course):
    client, cid = course
    d = client.get(f"/api/learn/curriculums/{cid}/").data
    assert d["status"] == "ready" and d["title"] == "AI Basics for Beginners"
    assert [len(s["subsections"]) for s in d["sections"]] == [2, 1]
    first, second = d["sections"][0]["subsections"]
    assert first["locked"] is False and second["locked"] is True  # quest-path unlocking
    assert d["progress"] == {"done": 0, "total": 3}
    assert first["activity_count"] == 0 and first["minutes"] is None  # not generated yet


def test_outline_lesson_card_details(course):
    client, cid = course
    lesson = _lesson(client, cid)
    first = client.get(f"/api/learn/curriculums/{cid}/").data["sections"][0]["subsections"][0]
    assert first["activity_count"] == len(lesson["activities"]) == 5
    assert first["minutes"] == 12 and 1 <= len(first["activity_types"]) <= 4
    assert isinstance(first["skills"], list)


def test_lesson_generated_and_keys_hidden(course):
    client, cid = course
    lesson = _lesson(client, cid)
    assert lesson["lesson_status"] == "ready" and "cricket" in lesson["explanation_md"]
    assert len(lesson["activities"]) == 5  # capped at 5
    blob = json.dumps(lesson)
    for secret in (
        '"correct"',
        '"order"',
        '"assign"',
        '"pairs"',
        "model_answer",
        "model_solution",
        '"blanks"',
    ):
        assert secret not in blob, secret


def test_grading_each_type(course):
    client, cid = course
    lesson = _lesson(client, cid)

    def attempt(act, answer):
        return client.post(
            f"/api/learn/activities/{act['id']}/attempt/", {"answer": answer}, format="json"
        ).data

    quiz = _act(lesson, "quiz")
    assert attempt(quiz, {"selected": [0]})["correct"] is False
    r = attempt(quiz, {"selected": [1]})
    assert r["correct"] is True and r["reveal"] == {"correct": [1]}

    fill = _act(lesson, "fill_blank")
    assert attempt(fill, {"blanks": {"1": "  Examples! "}})["score"] == 1.0
    assert attempt(fill, {"blanks": {"1": "magic"}})["score"] == 0.0

    seq = _act(lesson, "sequencing")
    right = ["s0", "s1", "s2"]
    assert attempt(seq, {"order": right})["score"] == 1.0
    assert 0 < attempt(seq, {"order": ["s1", "s2", "s0"]})["score"] < 1
    assert attempt(seq, {"order": ["s0"]})["score"] == 0.0

    cat = _act(lesson, "categorization")
    ids = {i["text"]: i["id"] for i in cat["payload"]["items"]}
    good = {ids["Spam filter"]: "AI", ids["Light switch"]: "Not AI"}
    assert attempt(cat, {"assign": good})["score"] == 1.0
    assert attempt(cat, {"assign": {ids["Spam filter"]: "AI"}})["score"] == 0.5

    match = _act(lesson, "matching")
    assert attempt(match, {"pairs": {"l0": "r0", "l1": "r1"}})["score"] == 1.0
    assert attempt(match, {"pairs": {"l0": "r1", "l1": "r0"}})["score"] == 0.0


def test_ai_graded_types_with_fake_llm(auth):
    client, _ = auth
    cid = client.post(
        "/api/learn/curriculums/",
        {"goal": "Learn Python programming", "level": "beginner", "domain": "python"},
        format="json",
    ).data["id"]
    # fake package has 8 activities; the cap keeps the first 5, so grade open_input/code directly via the model
    lesson = _lesson(client, cid)
    sub_id = lesson["id"]
    from apps.learning import activities as acts
    from apps.learning.models import Subsection

    sub = Subsection.objects.get(id=sub_id)
    payload, key = acts.build(
        {
            "type": "open_input",
            "title": "x",
            "prompt": "Explain AI",
            "model_answer": "learns from data",
            "rubric": ["learning"],
        },
        1,
    )
    a = Activity.objects.create(
        subsection=sub, order=9, type="open_input", title="x", payload=payload, key=key
    )
    r = client.post(
        f"/api/learn/activities/{a.id}/attempt/",
        {"answer": {"text": "It learns from examples"}},
        format="json",
    ).data
    assert r["score"] == 0.75 and r["correct"] is True and "examples" in r["feedback"]
    assert (
        client.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": {"text": ""}}, format="json").data[
            "score"
        ]
        == 0.0
    )


def test_complete_and_continue(course):
    client, cid = course
    lesson = _lesson(client, cid)
    assert client.get("/api/learn/continue/").data["subsection_id"] == lesson["id"]
    quiz = _act(lesson, "quiz")
    client.post(f"/api/learn/activities/{quiz['id']}/attempt/", {"answer": {"selected": [1]}}, format="json")
    recap = client.post(f"/api/learn/subsections/{lesson['id']}/complete/").data
    assert recap["total"] == 5 and recap["correct"] == 1 and recap["score"] == 0.2
    assert recap["next_subsection_id"] is not None and recap["key_points"]
    d = client.get(f"/api/learn/curriculums/{cid}/").data
    assert d["progress"]["done"] == 1 and d["sections"][0]["subsections"][1]["locked"] is False


def test_other_users_cannot_access(course, client):
    owner_client, cid = course
    lesson = _lesson(owner_client, cid)
    intruder = User.objects.create_user("x@example.com", "Intruder#2026")
    owner_client.force_authenticate(intruder)
    assert owner_client.get(f"/api/learn/curriculums/{cid}/").status_code == 404
    assert owner_client.get(f"/api/learn/subsections/{lesson['id']}/").status_code == 404
    act = lesson["activities"][0]["id"]
    assert (
        owner_client.post(
            f"/api/learn/activities/{act}/attempt/", {"answer": {"selected": [1]}}, format="json"
        ).status_code
        == 404
    )


def test_tamil_learner_gets_tamil_course(auth):
    client, _ = auth
    client.patch("/api/users/preferences/", {"mentor": {"reply_language": "ta"}}, format="json")
    res = client.post("/api/learn/curriculums/", {"goal": "AI அடிப்படைகள்"}, format="json")
    assert res.data["language"] == "ta"


def test_strict_schema_is_closed():
    from llm.prompts.curriculum import CurriculumOutline, LessonPackage
    from llm.structured import strict_schema

    s = json.dumps(strict_schema(LessonPackage))
    assert "$ref" not in s and "discriminator" not in s and '"additionalProperties": false' in s
    # Fields literally named "title" must survive keyword stripping (regression).
    outline = strict_schema(CurriculumOutline)
    assert "title" in outline["properties"] and "title" in outline["required"]
    sub = outline["properties"]["sections"]["items"]["properties"]["subsections"]["items"]
    assert sub["required"] == ["title", "objective", "skills"]


def test_stale_generation_expires_and_unblocks(auth):
    from datetime import timedelta

    from django.utils import timezone

    from apps.learning.models import Curriculum

    client, _ = auth
    me = User.objects.get(email="kavya@example.com")
    for _ in range(2):
        c = Curriculum.objects.create(owner=me, goal="stuck", status="generating")
        Curriculum.objects.filter(id=c.id).update(updated_at=timezone.now() - timedelta(minutes=30))
    res = client.post("/api/learn/curriculums/", {"goal": "Fresh course"}, format="json")
    assert res.status_code == 202
    assert Curriculum.objects.filter(goal="stuck", status="failed", error="timed_out").count() == 2


def test_flat_lesson_schema_is_small_and_converts():
    from llm.prompts.curriculum import FlatActivity, FlatLessonPackage, to_typed
    from llm.structured import strict_schema

    schema = json.dumps(strict_schema(FlatLessonPackage))
    assert "anyOf" not in schema and len(schema) < 3000  # no union, no nested batch-2 objects → small grammar
    quiz = FlatActivity(
        type="quiz", title="t", prompt="p", options=["a", "b"], correct=[1], explanation="e", text="ignored"
    )
    typed = to_typed(quiz)
    assert typed["type"] == "quiz" and typed["correct"] == [1] and "text" not in typed
    code = to_typed(
        FlatActivity(
            type="code",
            title="t",
            prompt="p",
            starter_code="",
            model_solution="print(1)",
            expected_output="1",
            rubric=["x"],
        )
    )
    assert code["language"] == "python"


def test_stuck_lesson_recovers_after_timeout(auth, settings):
    from datetime import timedelta

    from django.utils import timezone

    from apps.learning.models import Subsection

    client, _ = auth
    cid = client.post("/api/learn/curriculums/", {"goal": "AI basics"}, format="json").data["id"]
    sid = client.get(f"/api/learn/curriculums/{cid}/").data["sections"][0]["subsections"][0]["id"]
    # Simulate a job killed mid-flight 10 minutes ago.
    Subsection.objects.filter(id=sid).update(
        lesson_status="generating", generating_since=timezone.now() - timedelta(minutes=10)
    )
    assert client.get(f"/api/learn/subsections/{sid}/").data["lesson_status"] == "failed"
    assert (
        client.post(f"/api/learn/subsections/{sid}/start/").data["lesson_status"] == "ready"
    )  # retry regenerates


def test_interactive_rotation_gives_variety():
    from llm.prompts.curriculum import interactive_for

    seq = [interactive_for("ai", "AI basics", i) for i in range(4)]
    assert len(set(seq)) == 4  # four different interactive types across four lessons
    assert "viz" in {interactive_for("data", "Statistics", i) for i in range(8)}
    assert "roleplay" in {interactive_for("ai", "AI basics", i) for i in range(8)}
    assert "map" in {interactive_for("", "Rivers and monsoon geography", i) for i in range(8)}
    assert "map" not in {interactive_for("ai", "AI basics", i) for i in range(12)}
    assert "browser_task" in {interactive_for("ai", "Prompting with ChatGPT", i) for i in range(8)}
    assert "browser_task" not in {interactive_for("", "Rain in Tamil Nadu", i) for i in range(12)}
    assert "viz" not in {interactive_for("ai", "AI ethics", i) for i in range(8)}
