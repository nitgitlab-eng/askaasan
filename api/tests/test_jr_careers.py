"""Career role ladder (seeded links) and "plan my next 30 days": persistence, dated weeks, ticks, charging."""

from datetime import date, timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import Curriculum, Enrollment
from apps.orgs.models import Membership, Organization
from apps.paths.catalog import LADDER, seed
from apps.paths.models import CareerPath, CareerPlan
from apps.providers.models import UsageCounter

pytestmark = pytest.mark.django_db


@pytest.fixture
def learner():
    seed()
    u = User.objects.create_user("asha@example.com", "Career#Plan2026")
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def test_seeded_ladder_links_point_at_real_roles():
    seed()
    slugs = set(CareerPath.objects.values_list("slug", flat=True))
    for slug, (_, nxt, senior) in LADDER.items():
        assert slug in slugs and set(nxt) <= slugs and set(senior) <= slugs, slug
    da = CareerPath.objects.get(slug="data-analyst")
    assert (
        da.seniority == "entry"
        and "senior-data-analyst" in da.next_roles
        and da.senior_roles == ["analytics-manager"]
    )
    # re-seeding never overwrites an admin's edit
    CareerPath.objects.filter(slug="web-developer").update(next_roles=["data-analyst"])
    seed()
    assert CareerPath.objects.get(slug="web-developer").next_roles == ["data-analyst"]


def test_career_detail_has_ladder_with_visible_roles_only(learner):
    c, _ = learner
    o = Organization.objects.create(name="Secret Co", slug="secret", kind="company")
    CareerPath.objects.create(slug="secret-role", title="Secret role", summary="s", org=o)
    CareerPath.objects.filter(slug="data-analyst").update(next_roles=["senior-data-analyst", "secret-role"])
    lad = c.get("/api/paths/careers/data-analyst/").data["ladder"]
    assert lad["current"]["slug"] == "data-analyst"
    assert [x["slug"] for x in lad["next"]] == [
        "senior-data-analyst"
    ]  # another org's private role is not leaked
    assert [x["slug"] for x in lad["senior"]] == ["analytics-manager"]
    assert "research-assistant" in [
        x["slug"] for x in c.get("/api/paths/careers/data-scientist/").data["ladder"]["previous"]
    ]


def test_plan_generation_persists_dated_weeks_and_charges(learner):
    c, u = learner
    assert c.get("/api/paths/careers/data-analyst/plan/").data == {"plan": None}
    r = c.post("/api/paths/careers/data-analyst/plan/")
    assert r.status_code == 201, r.data
    p = r.data["plan"]
    today = timezone.localdate()
    assert [w["week"] for w in p["weeks"]] == [1, 2, 3, 4]
    assert (
        p["weeks"][0]["start"] == today.isoformat()
        and p["weeks"][3]["end"] == (today + timedelta(days=29)).isoformat()
    )
    goals = [g for w in p["weeks"] for g in w["goals"]]
    assert len(goals) == 5  # the out-of-range week-9 goal is dropped
    dues = [date.fromisoformat(g["due"]) for g in goals]
    assert dues == sorted(dues) and all(today <= d <= today + timedelta(days=29) for d in dues)
    assert all(g["skill"] and g["skill_name"] for g in goals)
    spread = next(g for g in goals if g["title"] == "Clean a messy sheet")
    assert (
        spread["course_id"] is None and spread["course_goal"] == "Clean a messy sheet"
    )  # unknown course id → new course goal
    assert p["people"][0]["role"] == "a senior data analyst in your team"
    assert UsageCounter.objects.get(user=u, metric="career_plan").amount == 1
    assert CareerPlan.objects.get(user=u).generations == 1
    # stored per learner: another learner sees nothing
    other = APIClient()
    other.force_authenticate(User.objects.create_user("ravi@example.com", "Career#Plan2026"))
    assert other.get("/api/paths/careers/data-analyst/plan/").data == {"plan": None}
    assert (
        other.post(
            f"/api/paths/careers/data-analyst/plan/goals/{goals[0]['id']}/", {"done": True}, format="json"
        ).status_code
        == 404
    )


def test_plan_ticks_link_course_and_regenerate_is_charged(learner):
    c, u = learner
    gid = c.post("/api/paths/careers/data-analyst/plan/").data["plan"]["weeks"][0]["goals"][0]["id"]
    r = c.post(f"/api/paths/careers/data-analyst/plan/goals/{gid}/", {"done": True}, format="json")
    assert r.data["plan"]["done"] == 1
    assert (
        c.post(
            f"/api/paths/careers/data-analyst/plan/goals/{gid}/", {"done": "yes"}, format="json"
        ).status_code
        == 400
    )
    assert (
        c.post("/api/paths/careers/data-analyst/plan/goals/nope/", {"done": True}, format="json").status_code
        == 404
    )
    mine = Curriculum.objects.create(owner=u, goal="SQL", title="SQL from zero", status="ready")
    theirs = Curriculum.objects.create(
        owner=User.objects.create_user("x@example.com", "Career#Plan2026"),
        goal="x",
        title="x",
        status="ready",
    )
    assert (
        c.post(
            f"/api/paths/careers/data-analyst/plan/goals/{gid}/", {"course_id": theirs.id}, format="json"
        ).status_code
        == 404
    )
    r = c.post(f"/api/paths/careers/data-analyst/plan/goals/{gid}/", {"course_id": mine.id}, format="json")
    g = r.data["plan"]["weeks"][0]["goals"][0]
    assert g["course_id"] == mine.id and g["link"] == f"/learn/{mine.id}"
    assert CareerPlan.objects.get(user=u).goals[0]["done"] is True  # persisted
    r = c.post("/api/paths/careers/data-analyst/plan/")
    assert r.status_code == 201 and r.data["plan"]["generations"] == 2 and r.data["plan"]["done"] == 0
    assert CareerPlan.objects.filter(user=u).count() == 1
    assert UsageCounter.objects.get(user=u, metric="career_plan").amount == 2
    UsageCounter.objects.filter(user=u, metric="career_plan").update(amount=5)
    assert c.post("/api/paths/careers/data-analyst/plan/").status_code == 429
    assert CareerPlan.objects.get(user=u).generations == 2  # a refused regeneration keeps the old plan


def test_plan_uses_only_courses_the_learner_can_open(learner, monkeypatch):
    c, u = learner
    opened = Curriculum.objects.create(
        owner=User.objects.create_user("t@example.com", "Career#Plan2026"),
        goal="g",
        title="Sheets 101",
        status="ready",
        kind="authored",
        published_at=timezone.now(),
    )
    Enrollment.objects.create(user=u, curriculum=opened)
    seen = {}
    from llm.prompts.journeys import CareerPlan as Schema

    def fake(task, system, user_msg, schema, **kw):
        seen["msg"] = user_msg
        return Schema.model_validate(
            {
                "summary": "s",
                "weeks": [{"week": 1, "theme": "t"}],
                "people": [],
                "goals": [
                    {
                        "week": 1,
                        "title": "Sheets",
                        "skill": "spreadsheets",
                        "course_id": opened.id,
                        "lesson_id": 0,
                        "course_goal": "",
                    }
                ],
            }
        )

    monkeypatch.setattr("llm.structured.complete_json_sync", fake)
    g = c.post("/api/paths/careers/data-analyst/plan/").data["plan"]["weeks"][0]["goals"][0]
    assert (
        f"{opened.id}: Sheets 101" in seen["msg"]
        and g["course_id"] == opened.id
        and g["link"] == f"/learn/{opened.id}"
    )


def test_plan_requires_visible_career(learner):
    c, _ = learner
    o = Organization.objects.create(name="Secret Co", slug="secret", kind="company")
    CareerPath.objects.create(slug="secret-role", title="Secret role", summary="s", org=o)
    assert c.post("/api/paths/careers/secret-role/plan/").status_code == 404
    Membership.objects.create(org=o, user=learner[1], role="learner")
    assert c.get("/api/paths/careers/secret-role/plan/").status_code == 200
