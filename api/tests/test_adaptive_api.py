"""Adaptive learning end to end (fake LLM): topic → scenario cards → course → concept graph → the learner's own path,
mastery from first attempts, completion gating with practice, the pre-test as diagnostic, and certificates."""

import pytest

from apps.adaptive.models import (
    ActivityConcept,
    Concept,
    ConceptEdge,
    ConceptLink,
    ConceptMastery,
    LearnerPath,
    LearningGoal,
    PathItem,
)
from apps.learning.models import Activity, Curriculum, Subsection, UserSubsectionState
from llm.providers import fake_provider

pytestmark = pytest.mark.django_db


def _goal(client, topic="AI", about="I run a small textile shop"):
    r = client.post("/api/adaptive/goals/", {"topic": topic, "about": about}, format="json")
    assert r.status_code == 201, r.data
    return r.data


def _adaptive_course(client):
    g = _goal(client)
    assert (
        client.post(f"/api/adaptive/goals/{g['id']}/choose/", {"index": 0}, format="json").status_code == 200
    )
    r = client.post(
        f"/api/adaptive/goals/{g['id']}/constraints/",
        {"prior": ["excel"], "no_code": True, "hours_week": 3, "deadline_weeks": 6},
        format="json",
    )
    assert r.status_code == 200 and r.data["status"] == "ready"
    r = client.post("/api/learn/curriculums/", {"goal_id": g["id"]}, format="json")
    assert r.status_code == 202, r.data
    return Curriculum.objects.get(id=r.data["id"])


def _subs(cur):
    return list(Subsection.objects.filter(section__curriculum=cur).order_by("section__order", "order"))


def _path(client, cur):
    r = client.get(f"/api/adaptive/courses/{cur.id}/path/")
    assert r.status_code == 200, r.data
    return r.data


def _kinds(path):
    return [
        (i["kind"], i["subsection"]["id"] if i["subsection"] else None, i["status"]) for i in path["items"]
    ]


# ── goal interview ───────────────────────────────────────────────────


def test_topic_only_gives_three_uses_and_a_foundations_track(auth):
    client, _ = auth
    g = _goal(client, about="")
    assert len(g["suggestions"]) == 4
    assert [s["foundations"] for s in g["suggestions"]] == [False, False, False, True]
    assert g["status"] == "suggested" and g["ai_left"] == 3


def test_choose_card_then_course_uses_the_scenario(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    goal = LearningGoal.objects.get(curriculum=cur)
    assert goal.status == "used"
    assert cur.goal.startswith("Build a WhatsApp order-reply helper")
    assert "Already knows: excel" in cur.notes and "don't want to write code" in cur.notes
    # the goal can't build a second course
    assert client.post("/api/learn/curriculums/", {"goal_id": goal.id}, format="json").status_code == 409


def test_custom_use_case_accepted(auth):
    client, _ = auth
    g = _goal(client)
    r = client.post(
        f"/api/adaptive/goals/{g['id']}/choose/", {"custom": "reply to my customers"}, format="json"
    )
    assert r.data["verdict"] == "accept" and r.data["status"] == "chosen"
    assert r.data["scenario"]["custom"] is True and r.data["scenario"]["asked"] == "reply to my customers"


def test_custom_use_case_split_offers_narrower_cards(auth, monkeypatch):
    client, _ = auth
    g = _goal(client)
    alt = {"title": "Build a menu page", "deliverable": "A page.", "level": "beginner", "weeks": 2}
    verdict = {
        "verdict": "split",
        "reason": "That is several courses; start here.",
        "scenario": {**alt, "foundations": False},
        "alternatives": [
            {**alt, "foundations": False},
            {**alt, "title": "Take orders by chat", "foundations": False},
        ],
    }
    monkeypatch.setitem(fake_provider.CANNED, "[[TASK:adaptive_verify]]", verdict)
    r = client.post(
        f"/api/adaptive/goals/{g['id']}/choose/", {"custom": "build an app like Swiggy"}, format="json"
    )
    assert r.data["verdict"] == "split" and r.data["reason"].startswith("That is several")
    assert r.data["status"] == "suggested"
    assert [s["title"] for s in r.data["suggestions"]] == [
        "Build a menu page",
        "Take orders by chat",
        "Understand AI basics first",  # the foundations track always stays
    ]


def test_custom_use_case_declined_keeps_foundations(auth, monkeypatch):
    client, _ = auth
    g = _goal(client)
    s = {
        "title": "Learn AI safety basics",
        "deliverable": "x",
        "level": "beginner",
        "weeks": 2,
        "foundations": False,
    }
    monkeypatch.setitem(
        fake_provider.CANNED,
        "[[TASK:adaptive_verify]]",
        {"verdict": "decline", "reason": "Not something we can teach.", "scenario": s, "alternatives": [s]},
    )
    r = client.post(
        f"/api/adaptive/goals/{g['id']}/choose/", {"custom": "hack my neighbour's wifi"}, format="json"
    )
    assert r.data["verdict"] == "decline" and r.data["status"] == "suggested"
    assert r.data["suggestions"][-1]["foundations"] is True


def test_goal_ai_calls_are_capped(auth):
    client, _ = auth
    g = _goal(client)
    url = f"/api/adaptive/goals/{g['id']}/choose/"
    LearningGoal.objects.filter(id=g["id"]).update(ai_calls=4)
    assert client.post(url, {"custom": "reply to customers"}, format="json").status_code == 429
    assert client.post(url, {"index": 1}, format="json").status_code == 200  # picking a card needs no AI


def test_goal_validation_and_ownership(auth, django_user_model):
    client, _ = auth
    assert client.post("/api/adaptive/goals/", {"topic": "x"}, format="json").status_code == 400
    g = _goal(client)
    assert client.post(f"/api/adaptive/goals/{g['id']}/constraints/", {}, format="json").status_code == 409
    assert (
        client.post(f"/api/adaptive/goals/{g['id']}/choose/", {"index": 9}, format="json").status_code == 400
    )
    other = django_user_model.objects.create_user(email="other@example.com", password="Tamil#Learn2026")
    from rest_framework.test import APIClient

    c2 = APIClient()
    c2.force_authenticate(other)
    assert c2.get(f"/api/adaptive/goals/{g['id']}/").status_code == 404
    assert c2.post("/api/learn/curriculums/", {"goal_id": g["id"]}, format="json").status_code == 409


def test_create_course_still_needs_a_goal(auth):
    client, _ = auth
    r = client.post("/api/learn/curriculums/", {"level": "beginner"}, format="json")
    assert r.status_code == 400 and "goal" in r.data


# ── concept graph ────────────────────────────────────────────────────


def test_ai_graph_is_cleaned_up(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    keys = set(Concept.objects.filter(curriculum=cur).values_list("key", flat=True))
    assert keys == {"ai-in-daily-life", "learning-from-examples", "prompting-basics", "ai-history"}
    edges = set(
        ConceptEdge.objects.filter(concept__curriculum=cur).values_list("prereq__key", "concept__key")
    )
    # self-loop and unknown prereq dropped
    assert edges == {("ai-in-daily-life", "learning-from-examples"), ("ai-in-daily-life", "prompting-basics")}
    s1, s2, s3 = _subs(cur)
    assert list(ConceptLink.objects.filter(subsection=s1).values_list("concept__key", flat=True)) == [
        "ai-in-daily-life",
        "ai-history",
    ]
    assert Concept.objects.get(curriculum=cur, key="ai-history").critical is False


def test_course_without_graph_gets_one_concept_per_lesson_without_ai(course_plain):
    client, cur = course_plain
    Concept.objects.filter(curriculum=cur).delete()
    path = _path(client, cur)
    assert Concept.objects.filter(curriculum=cur).count() == 3
    assert [k for k, _, _ in _kinds(path)] == ["lesson", "lesson", "lesson", "final"]


def test_lesson_activities_are_tagged(auth):
    client, cur = auth[0], _adaptive_course(auth[0])
    s1 = _subs(cur)[0]
    client.post(f"/api/learn/subsections/{s1.id}/start/")
    acts = Activity.objects.filter(subsection=s1, kind="lesson")
    assert acts.exists()
    assert ActivityConcept.objects.filter(activity__in=acts).count() == acts.count()


# ── the path ─────────────────────────────────────────────────────────


def test_goal_course_gets_a_path_at_once(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    assert LearnerPath.objects.filter(curriculum=cur).exists()
    s1, s2, s3 = _subs(cur)
    path = _path(client, cur)
    assert _kinds(path) == [
        ("lesson", s1.id, "pending"),
        ("lesson", s2.id, "pending"),
        ("lesson", s3.id, "pending"),
        ("final", None, "pending"),
    ]
    assert path["items"][0]["current"] is True and path["remaining"] == 4


def test_known_lesson_becomes_skip_check(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    _, _, s3 = _subs(cur)
    c = Concept.objects.get(curriculum=cur, key="prompting-basics")
    ConceptMastery.objects.create(user=cur.owner, concept=c, p_known=0.95, observations=4)
    path = LearnerPath.objects.get(curriculum=cur)
    from apps.adaptive.services import replan

    assert replan(path)["skip"] == 1
    data = _path(client, cur)
    assert ("skip_check", s3.id, "pending") in _kinds(data)
    assert data["changes"] == {"skip": 1} and data["version"] == 2


def _answer_all(client, sub, right: bool):
    lesson = client.post(f"/api/learn/subsections/{sub.id}/start/").data
    for a in lesson["activities"]:
        act = Activity.objects.get(id=a["id"])
        answer = _right(act) if right else _wrong(act)
        client.post(f"/api/learn/activities/{act.id}/attempt/", {"answer": answer}, format="json")


def _right(act):
    k = act.key
    if act.type in ("quiz", "diagram"):
        return {"selected": k["correct"]}
    if act.type == "fill_blank":
        return {"blanks": {b: a[0] for b, a in k["blanks"].items()}}
    if act.type == "sequencing":
        return {"order": k["order"]}
    if act.type == "categorization":
        return {"assign": k["assign"]}
    if act.type == "matching":
        return {"pairs": k["pairs"]}
    return {"text": "x"}


def _wrong(act):
    if act.type in ("quiz", "diagram"):
        return {
            "selected": [i for i in range(len(act.payload["options"])) if i not in act.key["correct"]][:1]
        }
    if act.type == "fill_blank":
        return {"blanks": {b: "zzz" for b in act.key["blanks"]}}
    if act.type == "sequencing":
        return {"order": list(reversed(act.key["order"]))}
    if act.type == "categorization":
        return {"assign": {i: "nowhere" for i in act.key["assign"]}}
    if act.type == "matching":
        return {"pairs": {}}
    return {"text": ""}


def test_first_attempts_move_concept_mastery(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    s1 = _subs(cur)[0]
    _answer_all(client, s1, right=True)
    m = ConceptMastery.objects.get(user=cur.owner, concept__key="ai-in-daily-life", concept__curriculum=cur)
    assert m.observations >= 3 and m.p_known >= 0.85
    seen = m.observations
    act = Activity.objects.filter(subsection=s1, kind="lesson").first()
    client.post(f"/api/learn/activities/{act.id}/attempt/", {"answer": _wrong(act)}, format="json")  # a retry
    m.refresh_from_db()
    assert m.observations == seen


def test_failing_a_lesson_requires_practice_then_lets_you_finish(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    s1 = _subs(cur)[0]
    _answer_all(client, s1, right=False)
    r = client.post(f"/api/learn/subsections/{s1.id}/complete/")
    assert r.status_code == 200 and r.data["passed"] is False
    assert r.data["remediation"] == {"kind": "remediation", "subsection_id": s1.id, "reason": "retry"}
    assert UserSubsectionState.objects.get(user=cur.owner, subsection=s1).status == "in_progress"
    path = _path(client, cur)
    assert _kinds(path)[:2] == [("remediation", s1.id, "pending"), ("lesson", s1.id, "pending")]
    assert path["items"][0]["reason"] == "retry"
    # still refused until practice is done
    assert client.post(f"/api/learn/subsections/{s1.id}/complete/").data["passed"] is False

    # practise: a fresh set, answered correctly, brings the concept back up
    assert client.post(f"/api/learn/subsections/{s1.id}/practice/").status_code == 200
    for _ in range(3):
        for a in Activity.objects.filter(subsection=s1, kind="practice"):
            if not a.attempts.exists():
                client.post(f"/api/learn/activities/{a.id}/attempt/", {"answer": _right(a)}, format="json")
        if PathItem.objects.filter(path__curriculum=cur, kind="remediation", status="done").exists():
            break
        Subsection.objects.filter(id=s1.id).update(practice_status="ready")
        client.post(f"/api/learn/subsections/{s1.id}/practice/")
    assert PathItem.objects.filter(path__curriculum=cur, kind="remediation", status="done").exists()

    r = client.post(f"/api/learn/subsections/{s1.id}/complete/")
    assert r.data["passed"] is True and r.data["score"] == 1.0  # the better of lesson and practice
    assert _kinds(_path(client, cur))[:2] == [("lesson", s1.id, "done"), ("remediation", s1.id, "done")]


def test_passing_a_lesson_is_not_gated(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    s1 = _subs(cur)[0]
    _answer_all(client, s1, right=True)
    r = client.post(f"/api/learn/subsections/{s1.id}/complete/")
    assert r.data["passed"] is True
    assert _kinds(_path(client, cur))[0] == ("lesson", s1.id, "done")


def test_non_adaptive_course_is_unchanged(course_plain):
    client, cur = course_plain
    s1 = _subs(cur)[0]
    _answer_all(client, s1, right=False)
    r = client.post(f"/api/learn/subsections/{s1.id}/complete/")
    assert r.data["passed"] is True
    assert UserSubsectionState.objects.get(user=cur.owner, subsection=s1).status == "completed"


def test_pretest_seeds_mastery_and_offers_skip_checks(auth, monkeypatch, django_capture_on_commit_callbacks):
    client, _ = auth
    cur = _adaptive_course(client)
    s1, s2, s3 = _subs(cur)
    items = [
        {
            "prompt": f"Q{i}",
            "options": ["a", "b", "c", "d"],
            "correct": 0,
            "explanation": "",
            "lesson": "Writing good prompts",
        }
        for i in range(4)
    ]
    monkeypatch.setitem(fake_provider.CANNED, "[[TASK:checkpoint_quiz]]", {"items": items})
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/api/study/courses/{cur.id}/checkpoint/")
    qs = client.get(f"/api/study/courses/{cur.id}/checkpoint/").data["questions"]
    r = client.post(
        f"/api/study/courses/{cur.id}/checkpoint/submit/",
        {"kind": "pre", "answers": {q["id"]: 0 for q in qs}},
        format="json",
    )
    assert r.status_code == 201
    m = ConceptMastery.objects.get(user=cur.owner, concept__key="prompting-basics", concept__curriculum=cur)
    assert m.p_known >= 0.9 and m.observations == 8
    assert ("skip_check", s3.id, "pending") in _kinds(_path(client, cur))


def test_skip_check_pass_completes_the_lesson(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    _, _, s3 = _subs(cur)
    c = Concept.objects.get(curriculum=cur, key="prompting-basics")
    ConceptMastery.objects.create(user=cur.owner, concept=c, p_known=0.95, observations=4)
    from apps.adaptive.services import replan

    replan(LearnerPath.objects.get(curriculum=cur))
    client.post(f"/api/learn/subsections/{s3.id}/start/")
    r = client.post(f"/api/study/lessons/{s3.id}/fast-track/", {}, format="json")
    assert r.status_code == 201
    answers = {}
    for q in r.data["questions"]:
        a = Activity.objects.get(id=q["id"])
        answers[str(a.id)] = {"selected": a.key["correct"]}
    r = client.post(f"/api/study/fast-track/{r.data['run_id']}/submit/", {"answers": answers}, format="json")
    assert r.data["passed"] is True
    assert ("lesson", s3.id, "done") in _kinds(_path(client, cur))


def test_skill_map(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    _answer_all(client, _subs(cur)[0], right=True)
    sm = client.get(f"/api/adaptive/courses/{cur.id}/skill-map/").data
    rows = {r["key"]: r for r in sm["concepts"]}
    assert rows["ai-in-daily-life"]["state"] == "mastered"
    assert rows["prompting-basics"]["state"] == "new"
    assert sm["critical_total"] == 3 and sm["total"] == 4
    assert {"prereq": "ai-in-daily-life", "concept": "prompting-basics"} in sm["edges"]


def test_path_needs_access(auth, django_user_model):
    client, _ = auth
    cur = _adaptive_course(client)
    from rest_framework.test import APIClient

    other = django_user_model.objects.create_user(email="o2@example.com", password="Tamil#Learn2026")
    c2 = APIClient()
    c2.force_authenticate(other)
    assert c2.get(f"/api/adaptive/courses/{cur.id}/path/").status_code == 404
    assert c2.get(f"/api/adaptive/courses/{cur.id}/skill-map/").status_code == 404


# ── shared courses + certificates ────────────────────────────────────


def test_two_learners_on_one_course_get_their_own_paths(shared_course):
    cur, (c1, u1), (c2, u2) = shared_course
    s1, s2, s3 = _subs(cur)
    c = Concept.objects.filter(curriculum=cur, lesson_links__subsection=s3).first()
    ConceptMastery.objects.create(user=u1, concept=c, p_known=0.95, observations=4)
    p1, p2 = _path(c1, cur), _path(c2, cur)
    assert ("skip_check", s3.id, "pending") in _kinds(p1)
    assert ("lesson", s3.id, "pending") in _kinds(p2)
    assert (
        Subsection.objects.filter(section__curriculum=cur).count() == 3
    )  # the syllabus itself never changes


def test_certificate_needs_critical_concepts_for_adaptive_learners(shared_course):
    from apps.credentials.services import course_completed

    cur, (c1, u1), (c2, u2) = shared_course
    for s in _subs(cur):
        _answer_all(c1, s, right=True)
        assert c1.post(f"/api/learn/subsections/{s.id}/complete/").data["passed"] is True
    _path(c1, cur)
    assert course_completed(u1, cur)
    ConceptMastery.objects.filter(user=u1, concept__curriculum=cur).update(p_known=0.5)
    assert not course_completed(u1, cur)
    LearnerPath.objects.filter(user=u1).delete()  # not adaptive for them: the old rule only
    assert course_completed(u1, cur)


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def course_plain(auth):
    client, _ = auth
    r = client.post("/api/learn/curriculums/", {"goal": "Understand AI basics"}, format="json")
    return client, Curriculum.objects.get(id=r.data["id"])


@pytest.fixture
def shared_course(django_user_model):
    """A published course two learners are enrolled in, with ready lessons."""
    from rest_framework.test import APIClient

    from apps.learning.models import Enrollment
    from apps.learning.services import generate_lesson

    author = django_user_model.objects.create_user(email="author@example.com", password="Tamil#Learn2026")
    ca = APIClient()
    ca.force_authenticate(author)
    r = ca.post("/api/learn/curriculums/", {"goal": "Understand AI basics"}, format="json")
    cur = Curriculum.objects.get(id=r.data["id"])
    for s in _subs(cur):
        generate_lesson(s.id)
    from django.utils import timezone

    Curriculum.objects.filter(id=cur.id).update(
        kind="authored", visibility="catalog", catalog_status="approved", published_at=timezone.now()
    )
    learners = []
    for email in ("l1@example.com", "l2@example.com"):
        u = django_user_model.objects.create_user(email=email, password="Tamil#Learn2026")
        Enrollment.objects.create(user=u, curriculum=cur)
        c = APIClient()
        c.force_authenticate(u)
        learners.append((c, u))
    cur.refresh_from_db()
    return cur, learners[0], learners[1]


def test_tutor_first_answer_counts_toward_mastery(auth):
    client, _ = auth
    cur = _adaptive_course(client)
    s1 = _subs(cur)[0]
    client.post(f"/api/learn/subsections/{s1.id}/start/")
    assert client.post(f"/api/learn/subsections/{s1.id}/tutor/", {}, format="json").status_code == 201
    client.post(f"/api/learn/subsections/{s1.id}/tutor/reply/", {"message": "From examples"}, format="json")
    m = ConceptMastery.objects.get(user=cur.owner, concept__key="ai-in-daily-life", concept__curriculum=cur)
    assert m.observations == 1


def test_course_detail_says_whether_it_is_adaptive(auth, course_plain):
    client, plain = course_plain
    assert client.get(f"/api/learn/curriculums/{plain.id}/").data["adaptive"] is False
    cur = _adaptive_course(client)
    assert client.get(f"/api/learn/curriculums/{cur.id}/").data["adaptive"] is True


def test_course_opens_only_after_its_concept_graph(auth, monkeypatch):
    """Regression (found on the live stack): the course was READY before the AI graph existed, so a learner who opened
    it in that gap got the fallback graph, which the AI graph then replaced under their path."""
    from apps.adaptive import graph

    seen = []
    real = graph.build

    def spy(cur, *, use_ai):
        seen.append(Curriculum.objects.get(pk=cur.pk).status)
        return real(cur, use_ai=use_ai)

    monkeypatch.setattr(graph, "build", spy)
    cur = _adaptive_course(auth[0])
    cur.refresh_from_db()
    assert seen == ["generating"] and cur.status == "ready"


def test_rebuilt_graph_replans_existing_paths(auth):
    from apps.adaptive import graph

    client, _ = auth
    cur = _adaptive_course(client)
    graph.build(cur, use_ai=True)  # e.g. the outline was regenerated
    path = LearnerPath.objects.get(curriculum=cur)
    assert not path.items.exclude(kind="final").filter(concept=None).exists()
