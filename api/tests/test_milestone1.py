"""Milestone 1: answer feedback, lesson feedback, DPA, decision-tree voice matching."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import Curriculum, Enrollment, LessonFeedback, Section, Subsection
from apps.learning.voice_match import local_match
from apps.mentor.models import AnswerFeedback, Conversation, Message
from apps.orgs.models import Membership, Organization

pytestmark = pytest.mark.django_db
PW = "Mile#2026pass"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def test_answer_feedback_only_on_own_ai_answers():
    c, u = client_for("a@x.in")
    other, ou = client_for("b@x.in")
    conv = Conversation.objects.create(user=u, title="t")
    mine = Message.objects.create(
        conversation=conv, role="assistant", content="Answer text", model="claude-sonnet-5-5"
    )
    q = Message.objects.create(conversation=conv, role="user", content="my question")
    assert (
        c.post(
            f"/api/assistant/feedback/message/{mine.id}/",
            {"rating": -1, "reason": "wrong", "comment": "bad maths"},
            format="json",
        ).status_code
        == 200
    )
    fb = AnswerFeedback.objects.get(user=u, object_id=mine.id)
    assert (
        fb.rating == -1
        and fb.reason == "wrong"
        and fb.excerpt == "Answer text"
        and fb.model == "claude-sonnet-5-5"
    )
    assert (
        c.post(f"/api/assistant/feedback/message/{mine.id}/", {"rating": 1}, format="json").status_code == 200
    )  # change vote
    assert AnswerFeedback.objects.get(user=u, object_id=mine.id).reason == ""
    assert (
        c.post(f"/api/assistant/feedback/message/{q.id}/", {"rating": 1}, format="json").status_code == 404
    )  # not an AI answer
    assert (
        other.post(f"/api/assistant/feedback/message/{mine.id}/", {"rating": 1}, format="json").status_code
        == 404
    )  # not theirs
    assert (
        c.post(f"/api/assistant/feedback/bogus/{mine.id}/", {"rating": 1}, format="json").status_code == 404
    )
    assert c.get(f"/api/assistant/conversations/{conv.id}/").data["messages"][0]["my_rating"] == 1
    c.post(f"/api/assistant/feedback/message/{mine.id}/", {"rating": 0}, format="json")
    assert not AnswerFeedback.objects.filter(user=u).exists()


def test_admin_sees_feedback_summary():
    c, u = client_for("a@x.in")
    conv = Conversation.objects.create(user=u, title="t")
    m = Message.objects.create(conversation=conv, role="assistant", content="Bad answer here")
    c.post(f"/api/assistant/feedback/message/{m.id}/", {"rating": -1, "reason": "unclear"}, format="json")
    admin, _ = client_for("boss@x.in", is_staff=True)
    fb = admin.get("/api/admin/overview/").data["feedback"]
    assert fb["down"] == 1 and fb["worst"][0]["excerpt"] == "Bad answer here"


@pytest.fixture
def lesson():
    _, owner = client_for("t@x.in", is_creator=True)
    cur = Curriculum.objects.create(
        owner=owner,
        kind=Curriculum.Kind.AUTHORED,
        goal="g",
        title="T",
        status="ready",
        visibility="link",
        published_at=timezone.now(),
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="S")
    return owner, cur, Subsection.objects.create(section=sec, order=0, title="L", lesson_status="ready")


def test_lesson_feedback_reaches_author_and_teacher(lesson):
    owner, cur, sub = lesson
    c, u = client_for("l@x.in")
    Enrollment.objects.create(user=u, curriculum=cur)
    assert (
        c.post(
            f"/api/learn/subsections/{sub.id}/feedback/",
            {"rating": 2, "difficulty": "hard", "comment": "too fast"},
            format="json",
        ).status_code
        == 200
    )
    assert (
        c.post(f"/api/learn/subsections/{sub.id}/feedback/", {"rating": 9}, format="json").status_code == 400
    )
    outsider, _ = client_for("o@x.in")
    assert (
        outsider.post(f"/api/learn/subsections/{sub.id}/feedback/", {"rating": 5}, format="json").status_code
        == 404
    )
    author = APIClient()
    author.force_authenticate(owner)
    fb = author.get(f"/api/lab/subsections/{sub.id}/").data["feedback"]
    assert fb == {"n": 1, "avg": 2.0, "hard": 1, "easy": 0, "comments": ["too fast"]}
    assert LessonFeedback.objects.count() == 1


def test_dpa_accept_by_admin_only_and_subprocessors_public():
    owner_c, owner = client_for("own@x.in")
    learner_c, learner = client_for("lr@x.in")
    org = Organization.objects.create(name="S", slug="s", created_by=owner)
    Membership.objects.create(org=org, user=owner, role="owner")
    Membership.objects.create(org=org, user=learner, role="learner")
    assert learner_c.post("/api/orgs/s/dpa/", {"accept": True}, format="json").status_code == 403
    assert owner_c.get("/api/orgs/s/dpa/").data["up_to_date"] is False
    assert owner_c.post("/api/orgs/s/dpa/", {"accept": False}, format="json").status_code == 400
    r = owner_c.post("/api/orgs/s/dpa/", {"accept": True}, format="json")
    assert r.data["up_to_date"] and r.data["accepted_by"] == "own@x.in"
    sp = APIClient().get("/api/legal/subprocessors/").data
    assert sp["version"] and isinstance(sp["subprocessors"], list)


def test_voice_choice_matching():
    opts = ["Write it in the exam", "Check the textbook", "Ask a friend"]
    assert local_match("the second one", opts) == 1
    assert local_match("option C", opts) == 2
    assert local_match("இரண்டாவது", opts) == 1
    assert local_match("check the textbook please", opts) == 1
    assert local_match("hmm", opts) is None
    c, _ = client_for("v@x.in")
    assert c.post(
        "/api/learn/match-choice/", {"spoken": "the first one", "options": opts}, format="json"
    ).data == {"index": 0, "via": "local"}
    r = c.post(
        "/api/learn/match-choice/", {"spoken": "the one about books", "options": opts}, format="json"
    ).data
    assert r["via"] == "ai" and r["index"] == 1  # fake model answers 1
    assert (
        c.post(
            "/api/learn/match-choice/", {"spoken": "x", "options": ["only one"]}, format="json"
        ).status_code
        == 400
    )
