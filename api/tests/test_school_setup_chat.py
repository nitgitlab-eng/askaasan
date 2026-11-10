"""Milestone 9 — 'Set up with Kili': proposals change nothing until an admin accepts them; org description grounds AI."""

import pytest

from apps.learning.models import Curriculum
from apps.orgs.models import Group, Membership, Organization, SubUnit
from apps.paths.models import CareerPath
from tests.test_school_units import client_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def org():
    CareerPath.objects.get_or_create(slug="data-analyst", defaults={"title": "Data analyst", "summary": "s"})
    admin, au = client_for("admin@kili.in")
    o = Organization.objects.create(name="Kili School", slug="ks", kind="school")
    Membership.objects.create(org=o, user=au, role="owner")
    mgr, mu = client_for("teacher@kili.in")
    Membership.objects.create(org=o, user=mu, role="manager")
    kid, ku = client_for("kid@kili.in")
    Membership.objects.create(org=o, user=ku, role="learner")
    return o, admin, au, mgr, kid


def test_proposals_apply_only_on_accept(org):
    o, admin, au, _, _ = org
    r = admin.post(
        "/api/orgs/ks/setup-chat/", {"message": "We are a school in Chennai, classes 6-10."}, format="json"
    )
    assert r.status_code == 200 and r.data["turns"] == 1
    props = r.data["messages"][1]["proposals"]
    assert [p["op"] for p in props] == [
        "set_description",
        "add_group",
        "set_target_roles",
        "set_feature",
        "course_idea",
        "add_unit",
    ]
    o.refresh_from_db()
    assert o.description == "" and not Group.objects.filter(name="Class 8 A").exists() and o.features == {}
    r = admin.post(
        "/api/orgs/ks/setup-chat/apply/", {"turn": 1, "accept": [0, 1, 2, 4], "reject": [3]}, format="json"
    )
    assert (
        r.status_code == 200
        and r.data["results"] == {"0": "", "1": "", "2": "", "4": ""}
        or all(v == "" for v in r.data["results"].values())
    )
    o.refresh_from_db()
    assert o.description.startswith("A Chennai school")
    assert Group.objects.filter(org=o, name="Class 8 A").exists()
    assert o.target_roles == ["data-analyst"]  # unknown role dropped
    assert o.features == {}  # rejected
    assert Curriculum.objects.filter(
        title="Science basics with AI", template_org=o, template_scope="org", owner=au
    ).exists()
    turn = r.data["messages"][1]
    assert turn["applied"] == [0, 1, 2, 4] and turn["rejected"] == [3]
    # accepting again (or accepting a rejected one) does nothing
    admin.post("/api/orgs/ks/setup-chat/apply/", {"turn": 1, "accept": [1, 3]}, format="json")
    assert Group.objects.filter(org=o, name="Class 8 A").count() == 1
    o.refresh_from_db()
    assert o.features == {}
    assert not SubUnit.objects.filter(org=o).exists()
    assert (
        admin.post("/api/orgs/ks/setup-chat/apply/", {"turn": 0, "accept": [0]}, format="json").status_code
        == 400
    )  # a user turn


def test_only_admins_chat_or_apply(org):
    o, admin, _, mgr, kid = org
    admin.post("/api/orgs/ks/setup-chat/", {"message": "Hello"}, format="json")
    for c in (mgr, kid):
        assert c.get("/api/orgs/ks/setup-chat/").status_code == 403
        assert c.post("/api/orgs/ks/setup-chat/", {"message": "hi"}, format="json").status_code == 403
        assert (
            c.post("/api/orgs/ks/setup-chat/apply/", {"turn": 1, "accept": [0, 1]}, format="json").status_code
            == 403
        )
    stranger, _ = client_for("x@y.in")
    assert (
        stranger.post("/api/orgs/ks/setup-chat/apply/", {"turn": 1, "accept": [0]}, format="json").status_code
        == 404
    )
    o.refresh_from_db()
    assert o.description == "" and not Group.objects.filter(org=o, name="Class 8 A").exists()


def test_turn_cap_and_reset(org):
    _, admin, _, _, _ = org
    for i in range(8):
        assert (
            admin.post("/api/orgs/ks/setup-chat/", {"message": f"answer {i}"}, format="json").status_code
            == 200
        )
    assert (
        admin.post("/api/orgs/ks/setup-chat/", {"message": "more"}, format="json").data["code"] == "chat_full"
    )
    assert admin.delete("/api/orgs/ks/setup-chat/").data["turns"] == 0


def test_description_grounds_org_course_generation(org):
    from apps.studio.context import generation_extras

    o, admin, au, _, _ = org
    admin.patch(
        "/api/orgs/ks/settings/",
        {"description": "A Coimbatore textile company training new supervisors."},
        format="json",
    )
    cur = Curriculum.objects.create(
        owner=au, goal="Safety", title="Safety", kind="authored", template_scope="org", template_org=o
    )
    rules, _ = generation_extras(cur, "safety")
    assert "About the organisation" in rules and "Coimbatore textile" in rules
    personal = Curriculum.objects.create(owner=au, goal="Mine", title="Mine", kind="authored")
    assert "About the organisation" not in generation_extras(personal, "x")[0]


def test_applied_markers_survive_later_turns(org):
    o, admin, *_ = org
    admin.post("/api/orgs/ks/setup-chat/", {"message": "hi"}, format="json")
    admin.post("/api/orgs/ks/setup-chat/apply/", {"turn": 1, "accept": [1], "reject": []}, format="json")
    r = admin.post("/api/orgs/ks/setup-chat/", {"message": "more"}, format="json")
    assert r.data["messages"][1]["applied"] == [1]
    admin.post("/api/orgs/ks/setup-chat/apply/", {"turn": 1, "accept": [1]}, format="json")
    assert Group.objects.filter(org=o, name="Class 8 A").count() == 1


def test_description_not_leaked_to_courses_of_other_orgs(org):
    from apps.orgs.models import Assignment
    from apps.studio.context import org_about

    o, admin, au, _, _ = org
    o.description = "Secret plans of Kili School"
    o.save()
    outsider, ou = client_for("author@else.in")
    foreign = Curriculum.objects.create(owner=ou, goal="g", title="Public course", kind="authored")
    Assignment.objects.create(org=o, curriculum=foreign)  # Kili School assigns someone else's course
    assert org_about(foreign) == ""
    mine = Curriculum.objects.create(owner=au, goal="g", title="Ours", kind="authored")
    Assignment.objects.create(org=o, curriculum=mine)
    assert "Secret plans" in org_about(mine)
