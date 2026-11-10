"""Class and org leaderboards: scopes from the caller's memberships, membership checks (teachers by class scope),
the org leaderboard switch, the learner opt-in, my_rank, and the cockpit class board."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.game.models import PlayerStats
from apps.game.services import award
from apps.orgs.models import Group, Membership, Organization


def person(email, name, xp=0):
    u = User.objects.create_user(email, "Board#2026pass")
    u.profile.display_name = name
    u.profile.save()
    if xp:
        award(u, "activity_correct", ref=f"x:{email}", xp=xp)
    return u


def client_for(u):
    c = APIClient()
    c.force_authenticate(u)
    return c


@pytest.fixture
def school(db):
    org = Organization.objects.create(name="Vidya School", slug="vidya", display_name="Vidya")
    everyone = Group.objects.create(org=org, name="Everyone")
    a = Group.objects.create(org=org, name="Class 8A")
    b = Group.objects.create(org=org, name="Class 8B")
    users = {
        "kavya": person("kavya@example.com", "Kavya R", 100),
        "arun": person("arun@example.com", "Arun K", 300),
        "meena": person("meena@example.com", "Meena S", 200),
        "teacher": person("t@example.com", "Teacher A"),
        "other_teacher": person("t2@example.com", "Teacher B"),
        "outsider": person("out@example.com", "Ravi Out", 900),
    }
    ms = {}
    for key, role in (
        ("kavya", "learner"),
        ("arun", "learner"),
        ("meena", "learner"),
        ("teacher", "manager"),
        ("other_teacher", "manager"),
    ):
        ms[key] = Membership.objects.create(org=org, user=users[key], role=role)
        everyone.members.add(ms[key])
    a.members.add(ms["kavya"], ms["arun"], ms["teacher"])
    b.members.add(ms["meena"], ms["other_teacher"])
    return {"org": org, "a": a, "b": b, "u": users}


def test_global_board_is_unchanged_and_lists_scopes(school):
    data = client_for(school["u"]["kavya"]).get("/api/game/leaderboard/").data
    assert data["scope"] == "global" and [r["name"] for r in data["rows"]] == [
        "Ravi",
        "Arun",
        "Meena",
        "Kavya",
    ]
    assert data["my_rank"] == 4 and data["me"]["rank"] == 4
    assert data["scopes"] == [
        {"scope": "global", "name": ""},
        {"scope": "org", "org": "vidya", "name": "Vidya"},
        {"scope": "class", "org": "vidya", "class": school["a"].id, "name": "Class 8A"},
    ]
    assert client_for(school["u"]["outsider"]).get("/api/game/leaderboard/").data["scopes"] == [
        {"scope": "global", "name": ""}
    ]


def test_org_board_only_members(school):
    data = client_for(school["u"]["kavya"]).get("/api/game/leaderboard/?scope=org&org=vidya").data
    assert data["scope"] == "org" and data["name"] == "Vidya"
    assert [r["name"] for r in data["rows"]] == ["Arun", "Meena", "Kavya"] and data["my_rank"] == 3
    r = client_for(school["u"]["outsider"]).get("/api/game/leaderboard/?scope=org&org=vidya")
    assert r.status_code == 404
    assert (
        client_for(school["u"]["kavya"]).get("/api/game/leaderboard/?scope=org&org=nope").status_code == 404
    )


def test_class_board_needs_the_class(school):
    a, b = school["a"].id, school["b"].id
    kavya = client_for(school["u"]["kavya"])
    data = kavya.get(f"/api/game/leaderboard/?scope=class&class={a}").data
    assert data["name"] == "Class 8A" and [r["name"] for r in data["rows"]] == ["Arun", "Kavya"]
    assert data["rows"][1]["me"] and data["my_rank"] == 2
    assert kavya.get(f"/api/game/leaderboard/?scope=class&class={b}").status_code == 404  # not her class
    assert kavya.get("/api/game/leaderboard/?scope=class&class=abc").status_code == 404
    assert kavya.get("/api/game/leaderboard/?scope=class&class=999999").status_code == 404
    assert (
        client_for(school["u"]["outsider"]).get(f"/api/game/leaderboard/?scope=class&class={a}").status_code
        == 404
    )
    assert kavya.get("/api/game/leaderboard/?scope=planet").status_code == 400


def test_teachers_see_classes_in_their_scope(school):
    a, b = school["a"].id, school["b"].id
    t2 = client_for(school["u"]["other_teacher"])
    assert t2.get(f"/api/game/leaderboard/?scope=class&class={b}").status_code == 200
    assert t2.get(f"/api/game/leaderboard/?scope=class&class={a}").status_code == 404
    owner = person("owner@example.com", "Owner")
    Membership.objects.create(org=school["org"], user=owner, role="owner")
    assert client_for(owner).get(f"/api/game/leaderboard/?scope=class&class={a}").status_code == 200


def test_opt_out_hides_the_learner_everywhere(school):
    PlayerStats.objects.filter(user=school["u"]["arun"]).update(show_on_leaderboard=False)
    arun = client_for(school["u"]["arun"])
    data = arun.get(f"/api/game/leaderboard/?scope=class&class={school['a'].id}").data
    assert [r["name"] for r in data["rows"]] == ["Kavya"] and data["my_rank"] is None
    assert data["me"]["xp"] >= 300  # still sees their own XP (plus the daily-goal bonus)


def test_org_switched_off(school):
    org = school["org"]
    org.features = {"leaderboard": False}
    org.save()
    kavya = client_for(school["u"]["kavya"])
    assert (
        kavya.get("/api/game/leaderboard/").data["code"] == "feature_off"
    )  # learners of the school: no boards
    t = client_for(school["u"]["teacher"])  # staff aren't blocked, but the school's boards are off
    assert t.get("/api/game/leaderboard/?scope=org&org=vidya").data["code"] == "feature_off"
    assert t.get(f"/api/game/leaderboard/?scope=class&class={school['a'].id}").status_code == 403
    assert [s["scope"] for s in t.get("/api/game/leaderboard/").data["scopes"]] == ["global"]


# ── Cockpit class board ──


def test_cockpit_class_board(school):
    a = school["a"]
    PlayerStats.objects.filter(user=school["u"]["kavya"]).update(show_on_leaderboard=False)
    r = client_for(school["u"]["teacher"]).get(f"/api/orgs/vidya/groups/{a.id}/board/")
    assert r.status_code == 200
    d = r.data
    assert d["class"] == {"id": a.id, "name": "Class 8A"} and d["enabled"] is True
    assert [row["name"] for row in d["rows"]] == ["Arun K"] and d["hidden"] == 1 and d["members"] == 2
    assert (d["week_end"] - d["week_start"]).days == 6


def test_cockpit_class_board_scope(school):
    b = school["b"].id
    assert client_for(school["u"]["teacher"]).get(f"/api/orgs/vidya/groups/{b}/board/").status_code == 403
    assert client_for(school["u"]["kavya"]).get(f"/api/orgs/vidya/groups/{b}/board/").status_code == 403
    assert client_for(school["u"]["outsider"]).get(f"/api/orgs/vidya/groups/{b}/board/").status_code in (
        403,
        404,
    )
    other = Organization.objects.create(name="Other", slug="other")
    g = Group.objects.create(org=other, name="X")
    assert client_for(school["u"]["teacher"]).get(f"/api/orgs/vidya/groups/{g.id}/board/").status_code == 404


def test_cockpit_board_top_ten(school):
    a = school["a"]
    org = school["org"]
    for i in range(12):
        u = person(f"l{i}@example.com", f"L{i}", 10 + i)
        a.members.add(Membership.objects.create(org=org, user=u, role="learner"))
    d = client_for(school["u"]["teacher"]).get(f"/api/orgs/vidya/groups/{a.id}/board/").data
    assert len(d["rows"]) == 10 and d["rows"][0]["name"] == "Arun K" and d["members"] == 14
