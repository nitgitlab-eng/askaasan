import json

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import ActivityAttempt, Curriculum, UserSubsectionState
from apps.review.models import MasteryRecord

pytestmark = pytest.mark.django_db
PW = "Creator#2026pass"


def client_for(email, creator=False, staff=False):
    u = User.objects.create_user(email, PW, is_creator=creator, is_staff=staff)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def creator():
    return client_for("teacher@aasan.test", creator=True)


def build_course(c):
    cid = c.post("/api/lab/courses/", {"goal": "Teach AI basics", "mode": "ai"}, format="json").data["id"]
    d = c.get(f"/api/lab/courses/{cid}/").data
    for s in d["sections"]:
        for b in s["subsections"]:
            assert c.post(f"/api/lab/subsections/{b['id']}/generate/").status_code == 202
    return cid, c.get(f"/api/lab/courses/{cid}/").data


def test_only_creators_can_use_lab(auth):
    learner, _ = auth
    assert learner.get("/api/lab/courses/").status_code == 403
    assert learner.post("/api/lab/courses/", {"goal": "x"}, format="json").status_code == 403
    staff, _ = client_for("admin2@aasan.test", staff=True)
    assert staff.get("/api/lab/courses/").status_code == 200  # admins can author too


def test_creators_cannot_touch_each_others_courses(creator):
    c, _ = creator
    cid, d = build_course(c)
    other, _ = client_for("other-teacher@aasan.test", creator=True)
    sub = d["sections"][0]["subsections"][0]["id"]
    assert other.get(f"/api/lab/courses/{cid}/").status_code == 404
    assert other.patch(f"/api/lab/subsections/{sub}/", {"title": "hacked"}, format="json").status_code == 404
    assert (
        other.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "link"}, format="json").status_code
        == 404
    )


def test_authored_drafts_stay_out_of_learner_library(creator):
    c, _ = creator
    cid, _ = build_course(c)
    assert all(x["id"] != cid for x in c.get("/api/learn/curriculums/").data)


def test_outline_editing_and_reorder(creator):
    c, _ = creator
    cid = c.post("/api/lab/courses/", {"goal": "Blank course", "mode": "blank"}, format="json").data["id"]
    d = c.post(f"/api/lab/courses/{cid}/sections/", {"title": "Intro"}, format="json").data
    sec = d["sections"][0]["id"]
    for t in ("A", "B", "C"):
        d = c.post(
            f"/api/lab/sections/{sec}/subsections/", {"title": t, "objective": "o"}, format="json"
        ).data
    ids = [b["id"] for b in d["sections"][0]["subsections"]]
    d = c.post(f"/api/lab/courses/{cid}/reorder/", {"subsections": {str(sec): ids[::-1]}}, format="json").data
    assert [b["title"] for b in d["sections"][0]["subsections"]] == ["C", "B", "A"]
    assert (
        c.post(
            f"/api/lab/courses/{cid}/reorder/", {"subsections": {str(sec): ids[:1]}}, format="json"
        ).status_code
        == 400
    )


def test_activity_edit_is_validated_and_keys_regenerated(creator):
    c, _ = creator
    _, d = build_course(c)
    sub = d["sections"][0]["subsections"][0]["id"]
    lesson = c.get(f"/api/lab/subsections/{sub}/").data
    quiz = next(a for a in lesson["activities"] if a["type"] == "quiz")
    assert quiz["editable"] and quiz["source"]["correct"] == [1]
    bad = {**quiz["source"], "correct": [9]}
    r = c.patch(f"/api/lab/activities/{quiz['id']}/", {"source": bad}, format="json")
    assert r.status_code == 400 and r.data["code"] == "invalid_activity"
    good = {**quiz["source"], "options": ["Maps ETA", "Torch"], "correct": [0]}
    assert c.patch(f"/api/lab/activities/{quiz['id']}/", {"source": good}, format="json").status_code == 200
    from apps.learning.models import Activity

    assert Activity.objects.get(id=quiz["id"]).key["correct"] == [0]
    # AI single activity + hand-written activity
    ai = c.post(
        f"/api/lab/subsections/{sub}/activities/", {"type": "quiz", "instructions": "cricket"}, format="json"
    )
    assert ai.status_code == 201 and ai.data["title"] == "Teacher quiz"
    hw = c.post(
        f"/api/lab/subsections/{sub}/activities/",
        {
            "type": "matching",
            "source": {
                "title": "M",
                "prompt": "p",
                "pairs": [{"left": "a", "right": "1"}, {"left": "b", "right": "2"}],
                "explanation": "e",
            },
        },
        format="json",
    )
    assert hw.status_code == 201


def test_publish_requires_ready_lessons(creator):
    c, _ = creator
    cid = c.post("/api/lab/courses/", {"goal": "Empty", "mode": "blank"}, format="json").data["id"]
    sec = c.post(f"/api/lab/courses/{cid}/sections/", {"title": "S"}, format="json").data["sections"][0]["id"]
    c.post(f"/api/lab/sections/{sec}/subsections/", {"title": "Not written yet"}, format="json")
    r = c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "link"}, format="json")
    assert r.status_code == 409 and r.data["lessons"] == ["Not written yet"]


def test_share_link_enroll_and_per_learner_progress(creator, auth):
    c, _ = creator
    cid, d = build_course(c)
    token = c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "link"}, format="json").data[
        "share_token"
    ]
    learner, _ = auth
    sub = d["sections"][0]["subsections"][0]["id"]
    assert learner.get(f"/api/learn/curriculums/{cid}/").status_code == 404  # not enrolled yet
    assert learner.post(f"/api/share/{token}/enroll/").data["curriculum_id"] == cid
    assert any(
        x["id"] == cid and x["kind"] == "authored" for x in learner.get("/api/learn/curriculums/").data
    )
    lesson = learner.post(f"/api/learn/subsections/{sub}/start/").data
    quiz = next(a for a in lesson["activities"] if a["type"] == "quiz")
    assert learner.post(
        f"/api/learn/activities/{quiz['id']}/attempt/", {"answer": {"selected": [1]}}, format="json"
    ).data["correct"]
    learner.post(f"/api/learn/subsections/{sub}/complete/")
    me = User.objects.get(email="kavya@example.com")
    teacher = User.objects.get(email="teacher@aasan.test")
    assert UserSubsectionState.objects.filter(user=me, subsection_id=sub, status="completed").exists()
    assert not UserSubsectionState.objects.filter(
        user=teacher, subsection_id=sub
    ).exists()  # progress is per learner
    assert (
        MasteryRecord.objects.filter(user=me).exists()
        and ActivityAttempt.objects.filter(user=me).count() == 1
    )
    # learners can't edit or regenerate a shared course
    assert learner.patch(f"/api/lab/subsections/{sub}/", {"title": "x"}, format="json").status_code == 403
    # unpublishing revokes access
    c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "private"}, format="json")
    assert learner.get(f"/api/learn/curriculums/{cid}/").status_code == 404


def test_learner_never_triggers_generation_on_shared_course(creator, auth):
    c, _ = creator
    cid = c.post("/api/lab/courses/", {"goal": "Half done", "mode": "blank"}, format="json").data["id"]
    sec = c.post(f"/api/lab/courses/{cid}/sections/", {"title": "S"}, format="json").data["sections"][0]["id"]
    d = c.post(f"/api/lab/sections/{sec}/subsections/", {"title": "Ready"}, format="json").data
    sub = d["sections"][0]["subsections"][0]["id"]
    c.post(f"/api/lab/subsections/{sub}/generate/")
    token = c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "link"}, format="json").data[
        "share_token"
    ]
    # creator later adds an unwritten lesson after publishing
    d = c.post(f"/api/lab/sections/{sec}/subsections/", {"title": "Later"}, format="json").data
    later = d["sections"][0]["subsections"][1]["id"]
    learner, _ = auth
    learner.post(f"/api/share/{token}/enroll/")
    r = learner.post(f"/api/learn/subsections/{later}/start/")
    assert r.status_code == 409 and r.data["code"] == "lesson_not_ready"


def test_guest_first_lesson(creator):
    c, _ = creator
    cid, d = build_course(c)
    anon = APIClient()
    assert (
        anon.get(f"/api/share/{Curriculum.objects.get(id=cid).share_token}/").status_code == 404
    )  # draft: dead link
    token = c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "link"}, format="json").data[
        "share_token"
    ]
    info = anon.get(f"/api/share/{token}/").data
    assert info["enrolled"] is False and info["sections"]
    g = anon.get(f"/api/share/{token}/lesson/").data
    blob = json.dumps(g)
    for secret in ('"correct"', "model_answer", "model_solution", '"assign"'):
        assert secret not in blob
    quiz = next(a for a in g["activities"] if a["type"] == "quiz")
    assert anon.post(
        f"/api/share/{token}/attempt/{quiz['id']}/", {"answer": {"selected": [1]}}, format="json"
    ).data["correct"]
    assert ActivityAttempt.objects.count() == 0  # guests leave no trace
    locked = next((a for a in g["activities"] if a["locked"]), None)
    if locked:
        assert (
            anon.post(
                f"/api/share/{token}/attempt/{locked['id']}/", {"answer": {"text": "x"}}, format="json"
            ).status_code
            == 403
        )
    second = d["sections"][0]["subsections"][1]["id"]
    from apps.learning.models import Activity

    other = Activity.objects.filter(subsection_id=second).first()
    assert (
        anon.post(f"/api/share/{token}/attempt/{other.id}/", {"answer": {}}, format="json").status_code == 404
    )  # only lesson 1
    assert anon.post(f"/api/share/{token}/enroll/").status_code == 401


def test_catalog_moderation(creator, auth):
    c, _ = creator
    cid, _ = build_course(c)
    c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "catalog"}, format="json")
    learner, _ = auth
    assert learner.get("/api/catalog/").data == []  # pending → hidden
    assert learner.get("/api/admin/catalog/").status_code == 403
    admin, _ = client_for("mod@aasan.test", staff=True)
    assert [x["id"] for x in admin.get("/api/admin/catalog/").data] == [cid]
    assert (
        admin.post(f"/api/admin/catalog/{cid}/", {"decision": "approve"}, format="json").data[
            "catalog_status"
        ]
        == "approved"
    )
    cards = learner.get("/api/catalog/").data
    assert [x["id"] for x in cards] == [cid] and cards[0]["creator"]
    assert admin.post(
        "/api/admin/creators/", {"email": "kavya@example.com", "is_creator": True}, format="json"
    ).data["is_creator"]
    assert learner.get("/api/lab/courses/").status_code == 200  # newly granted
