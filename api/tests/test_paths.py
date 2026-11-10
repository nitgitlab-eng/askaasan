"""Milestone 2: skills, recommendations, curated paths, careers + assessments, placement, onboarding interview, org heat-map."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import Curriculum, LessonFeedback, Section, Subsection, UserSubsectionState
from apps.orgs.models import Membership, Organization
from apps.paths.models import CareerPath, RoleAssessment, Skill, UserSkill
from apps.paths.services import match_skills
from apps.review.models import MasteryRecord, ReviewCard

pytestmark = pytest.mark.django_db
PW = "Paths#2026pass"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def test_catalog_seeded_and_skill_matching():
    assert Skill.objects.count() >= 30 and CareerPath.objects.count() >= 10
    assert {"sql", "data-analysis"} <= match_skills(["SQL queries", "Data analysis with pandas"])
    assert "prompt-engineering" in match_skills(["Prompting basics"])


def test_follow_hide_reorder_and_bulk():
    c, u = client_for("s@x.in")
    c.post("/api/paths/skills/python/", {"followed": True}, format="json")
    c.post("/api/paths/skills/sql/", {"followed": True, "self_rating": 3}, format="json")
    out = {
        s["slug"]: s
        for s in c.post("/api/paths/skills/reorder/", {"slugs": ["sql", "python"]}, format="json").data
    }
    assert out["sql"]["order"] == 0 and out["python"]["order"] == 1 and out["sql"]["self_rating"] == 3
    out = {s["slug"]: s for s in c.post("/api/paths/skills/sql/", {"hidden": True}, format="json").data}
    assert out["sql"]["hidden"] and not out["sql"]["followed"]
    assert c.post("/api/paths/skills/sql/", {"self_rating": 9}, format="json").status_code == 400
    c.post(
        "/api/paths/skills/bulk/",
        {"skills": [{"slug": "ai-basics", "self_rating": 2}, {"slug": "nope"}]},
        format="json",
    )
    assert UserSkill.objects.get(user=u, skill__slug="ai-basics").followed


def _course(owner, title, skills, n=3):
    cur = Curriculum.objects.create(owner=owner, goal=title, title=title, status="ready", skills=skills)
    sec = Section.objects.create(curriculum=cur, order=0, title="S")
    subs = [
        Subsection.objects.create(
            section=sec, order=i, title=f"{title} {i}", skills=skills, lesson_status="ready"
        )
        for i in range(n)
    ]
    return cur, subs


def test_recommendations_are_adaptive_and_respect_hidden():
    c, u = client_for("r@x.in")
    cur, subs = _course(u, "SQL from zero", ["SQL"])
    _, ai = _course(u, "Prompting", ["Prompt engineering"])
    UserSubsectionState.objects.create(
        user=u, subsection=subs[0], status="completed", completed_at=timezone.now()
    )
    MasteryRecord.objects.create(user=u, subsection=subs[0], p_known=0.3)
    MasteryRecord.objects.create(user=u, subsection=ai[0], p_known=0.2)
    from apps.learning.models import Activity

    a = Activity.objects.create(subsection=subs[0], order=0, type="quiz", title="q", payload={}, key={})
    ReviewCard.objects.create(user=u, activity=a, due=timezone.now())
    c.post("/api/paths/skills/sql/", {"followed": True}, format="json")
    c.post("/api/paths/skills/data-visualization/", {"followed": True}, format="json")
    c.post("/api/paths/skills/prompt-engineering/", {"hidden": True}, format="json")
    LessonFeedback.objects.create(user=u, subsection=subs[1], rating=2, difficulty="hard")
    recs = c.get("/api/paths/recommendations/").data
    kinds = [r["kind"] for r in recs]
    assert kinds[0] == "review" and "practice" in kinds and "start" in kinds
    assert not any("Prompting" in r["title"] for r in recs)  # hidden skill excluded
    assert any(r["why"]["key"] == "tooHard" for r in recs)
    assert any(
        r["kind"] == "start" and r["link"] == "/learn?new=data-visualization" for r in recs
    )  # slug, read by the Library
    c.patch("/api/users/preferences/", {"learning": {"adaptive": False}}, format="json")
    assert {r["kind"] for r in c.get("/api/paths/recommendations/").data} <= {"review", "continue"}


def test_curated_path_join_and_link_step():
    c, u = client_for("p@x.in")
    lst = c.get("/api/paths/curated/").data
    assert any(p["slug"] == "ai-for-everyone" for p in lst)
    d = c.post("/api/paths/curated/ai-for-everyone/join/").data
    assert d["joined"] and UserSkill.objects.filter(user=u, followed=True).exists()
    cur, _ = _course(u, "AI basics", ["AI"])
    d = c.post("/api/paths/curated/ai-for-everyone/steps/0/", {"curriculum_id": cur.id}, format="json").data
    assert d["steps"][0]["course"]["course_id"] == cur.id and d["steps"][0]["course"]["total"] == 3
    other, ou = client_for("q@x.in")
    theirs, _ = _course(ou, "x", [])
    assert (
        c.post(
            "/api/paths/curated/ai-for-everyone/steps/1/", {"curriculum_id": theirs.id}, format="json"
        ).status_code
        == 404
    )
    assert (
        c.post("/api/paths/curated/", {"title": "t", "steps": [{"goal": "g"}]}, format="json").status_code
        == 403
    )  # staff only


def test_career_assessment_keys_hidden_levels_and_gap_follow():
    c, u = client_for("c@x.in")
    r = c.post("/api/paths/careers/data-analyst/assessment/").data
    assert "correct" not in str(r["questions"])
    res = c.post(
        f"/api/paths/assessments/{r['id']}/submit/", {"answers": {"0": 1, "1": 0}}, format="json"
    ).data
    assert res["levels"]["spreadsheets"] == 4 and res["levels"]["sql"] == 1
    assert UserSkill.objects.get(user=u, skill__slug="sql").followed  # gap → followed
    d = c.get("/api/paths/careers/data-analyst/").data
    assert 0 < d["readiness"] < 1 and any(x["gap"] > 0 for x in d["requirements"])
    other, _ = client_for("d@x.in")
    assert (
        other.post(f"/api/paths/assessments/{r['id']}/submit/", {"answers": {}}, format="json").status_code
        == 404
    )
    assert RoleAssessment.objects.get(pk=r["id"]).completed_at


def test_placement_sets_level():
    c, u = client_for("pl@x.in")
    r = c.post("/api/paths/placement/", {"goal": "Learn data science"}, format="json").data
    assert len(r["questions"]) == 5 and "correct" not in str(r["questions"])
    res = c.post(
        f"/api/paths/placement/{r['id']}/submit/", {"answers": {str(i): 0 for i in range(5)}}, format="json"
    ).data
    assert res["level"] == "advanced"
    u.profile.refresh_from_db()
    assert u.profile.level == "advanced"


def test_onboarding_interview_and_apply():
    c, u = client_for("o@x.in")
    r = c.post(
        "/api/paths/onboarding-chat/",
        {"messages": [{"role": "user", "content": "I want to learn prompting for my job"}]},
        format="json",
    ).data
    assert r["reply"] and "profile" in r
    c.post(
        "/api/paths/onboarding-apply/", {"profile": {**r["profile"], "minutes_per_day": 30}}, format="json"
    )
    u.refresh_from_db()
    assert u.preferences.data["learning"]["daily_goal_minutes"] == 30
    assert UserSkill.objects.filter(user=u, skill__slug="prompt-engineering", followed=True).exists()


def test_org_competency_heatmap():
    oc, owner = client_for("own@x.in")
    _, learner = client_for("l@x.in")
    org = Organization.objects.create(name="S", slug="s", created_by=owner)
    Membership.objects.create(org=org, user=owner, role="owner")
    Membership.objects.create(org=org, user=learner, role="learner")
    UserSkill.objects.create(user=learner, skill=Skill.objects.get(slug="sql"), assessed_level=2)
    assert oc.get("/api/orgs/s/competencies/").data["career"] is None
    d = oc.patch("/api/orgs/s/competencies/", {"career": "data-analyst"}, format="json").data
    assert d["career"]["slug"] == "data-analyst" and d["rows"][0]["levels"]["sql"] == 2
    lc = APIClient()
    lc.force_authenticate(learner)
    assert lc.get("/api/orgs/s/competencies/").status_code == 403
