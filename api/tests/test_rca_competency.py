"""M10 rca: role-play competency analytics — learners × concepts matrix, funnel, stuck flags, per-concept drill-down
(AI summary cached + charged), export safety and class-scope permissions."""

import csv
import io
import zipfile
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.orgs import teach_rp
from apps.orgs.models import Assignment, Group, Membership, Organization, TeachInsight
from apps.providers.models import UsageCounter
from apps.roleplay.models import RolePlaySession, RolePlayTurn, Scenario

pytestmark = pytest.mark.django_db
PW = "Rca#2026passwd"


def user(email, name="X"):
    u = User.objects.create_user(email, PW)
    u.profile.display_name = name
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def member(org, u, role, group=None):
    m = Membership.objects.create(org=org, user=u, role=role)
    if group:
        group.members.add(m)
    return m


def _result(score, met=(True, False), comp=3):
    return {
        "overall": score,
        "competencies": [
            {
                "name": "Empathy",
                "score": comp,
                "evidence": [],
                "comment": "Shows real care" if comp >= 3 else "Sounds cold",
            }
        ],
        "objectives": [{"text": "Listen", "met": met[0]}, {"text": "Agree next step", "met": met[1]}],
        "strengths": [],
        "improvements": [],
        "better_phrasing": [],
        "summary": "ok",
    }


@pytest.fixture
def school():
    owner_c, owner = user("principal@rca.in", "Meena")
    slug = owner_c.post("/api/orgs/", {"name": "RCA School", "kind": "school"}, format="json").data["slug"]
    org = Organization.objects.get(slug=slug)
    ga, gb = Group.objects.create(org=org, name="8-A"), Group.objects.create(org=org, name="8-B")
    ta_c, ta = user("ta@rca.in", "Anitha")
    member(org, ta, "manager", ga)
    tb_c, tb = user("tb@rca.in", "Bala")
    member(org, tb, "manager", gb)
    learners = {}
    for email, name, g in (
        ("k1@rca.in", "=HYPERLINK(evil)", ga),
        ("k2@rca.in", "Kavin", ga),
        ("k3@rca.in", "Divya", ga),
        ("k4@rca.in", "Elan", gb),
    ):
        c, u = user(email, name)
        member(org, u, "learner", g)
        learners[name] = (c, u)
    sc = Scenario.objects.create(
        source="custom",
        owner=owner,
        title="Calm a worried parent",
        summary="s",
        learner_role="Teacher",
        character={"name": "Mrs. Rao", "persona": "worried", "goal": "SECRET-GOAL", "style": "s"},
        setting="PTA",
        objectives=["Listen", "Agree next step"],
        competencies=[{"name": "Empathy", "description": "d"}],
        opening_line="Hello?",
    )
    a = owner_c.post(f"/api/orgs/{slug}/assignments/", {"scenario_id": sc.id}, format="json")  # whole org
    assert a.status_code == 201
    Assignment.objects.filter(pk=a.data["id"]).update(
        created_at=timezone.now() - timedelta(days=30)
    )  # sessions are back-dated below
    return {
        "slug": slug,
        "org": org,
        "owner": (owner_c, owner),
        "ta": (ta_c, ta),
        "tb": (tb_c, tb),
        "l": learners,
        "sc": sc,
        "a": Assignment.objects.get(pk=a.data["id"]),
    }


def _session(u, a, score=None, days_ago=0, coach=None, **kw):
    s = RolePlaySession.objects.create(
        user=u,
        scenario=a.scenario,
        assignment=a,
        status="completed" if score is not None else "active",
        result=_result(score, **kw) if score is not None else None,
    )
    when = timezone.now() - timedelta(days=days_ago)
    RolePlaySession.objects.filter(pk=s.pk).update(
        started_at=when, ended_at=when + timedelta(minutes=5) if score is not None else None
    )
    s.refresh_from_db()
    for c in coach or []:
        RolePlayTurn.objects.create(session=s, role="learner", text="hi", coach=c)
    return s


def _coach(o0, o1, r0="", r1="", c0=1, cr=""):
    return {
        "objectives": [{"score": o0, "reason": r0}, {"score": o1, "reason": r1}],
        "competencies": [{"score": c0, "reason": cr}],
        "checks": [],
    }


@pytest.fixture
def data(school):
    a, L = school["a"], school["l"]
    # k1: passes first time; objective 1 met via coach (3), objective 2 only partly
    _session(
        L["=HYPERLINK(evil)"][1],
        a,
        85,
        coach=[_coach(3, 1, "Asked what worried her", "Did not propose a meeting")],
        met=(True, False),
        comp=4,
    )
    # k2: three attempts, never passes, no improvement → many_attempts + no_improvement
    for sc_ in (60, 55, 58):
        _session(L["Kavin"][1], a, sc_, days_ago=3, met=(False, False), comp=2)
    # k3: started 10 days ago, never finished → stalled
    _session(L["Divya"][1], a, None, days_ago=10, coach=[_coach(1, 0, "Interrupted the parent")])
    # k4 (other class): not started
    return school


def test_build_matrix_funnel_stuck_on_fixtures(data):
    a = data["a"]
    from apps.orgs.perms import require
    from apps.orgs.teach import assignment_learners

    me = require(data["owner"][1], data["slug"], "manager")
    out = teach_rp.build(a, assignment_learners(me, a), timezone.now(), 7)
    assert [c["key"] for c in out["concepts"]] == ["o0", "o1", "c0"]
    rows = {r["name"]: r for r in out["matrix"]}
    k1 = rows["=HYPERLINK(evil)"]
    assert k1["cells"]["o0"] == {"level": 3, "passed": True}
    assert k1["cells"]["o1"] == {"level": 1, "passed": False}
    assert k1["cells"]["c0"] == {"level": 4, "passed": True} and k1["passed"] and k1["flags"] == []
    assert rows["Kavin"]["cells"]["o0"] == {"level": 0, "passed": False}
    assert (
        rows["Divya"]["cells"]["c0"]["level"] is None
    )  # coach competency scale isn't mixed into the 1-5 matrix
    assert rows["Elan"]["cells"]["o0"]["level"] is None
    assert set(rows["Kavin"]["flags"]) == {"many_attempts", "no_improvement"}
    assert rows["Divya"]["flags"] == ["stalled"]
    funnel = {f["stage"]: f for f in out["funnel"]}
    assert [funnel[k]["count"] for k in ("assigned", "started", "completed", "passed")] == [4, 3, 2, 1]
    assert funnel["passed"]["pct"] == 0.25
    o0 = out["concepts"][0]
    assert (
        o0["attempted"] == 3 and o0["passed"] == 1 and o0["rate"] == round(1 / 3, 3) and o0["of_all"] == 0.25
    )
    assert {s["name"] for s in out["stuck"]} == {"Kavin", "Divya"}
    # threshold respected: with N = 30 days Divya isn't stalled yet
    out30 = teach_rp.build(a, assignment_learners(me, a), timezone.now(), 30)
    assert "Divya" not in {s["name"] for s in out30["stuck"]}


def test_stuck_reasons_edges():
    now = timezone.now()

    class S:
        def __init__(self, score, days):
            self.status = "completed" if score is not None else "active"
            self.result = {"overall": score} if score is not None else None
            self.started_at = now - timedelta(days=days)

    assert teach_rp.stuck_reasons([], now, 7) == []
    assert teach_rp.stuck_reasons([S(None, 2)], now, 7) == []
    assert teach_rp.stuck_reasons([S(40, 2), S(55, 1)], now, 7) == []  # improving, only 2 tries
    assert teach_rp.stuck_reasons([S(40, 3), S(30, 2), S(90, 1)], now, 7) == []  # passed in the end
    assert teach_rp.stuck_reasons([S(40, 3), S(50, 2), S(60, 1)], now, 7) == ["many_attempts"]


def test_report_endpoint_scope_and_permissions(data):
    slug, a = data["slug"], data["a"]
    url = f"/api/orgs/{slug}/teach/assignments/{a.id}/roleplay/"
    r = data["owner"][0].get(url)
    assert r.status_code == 200 and len(r.data["competency"]["matrix"]) == 4
    # teacher of 8-B sees only their class on the org-wide assignment
    rb = data["tb"][0].get(url).data["competency"]
    assert (
        [m["name"] for m in rb["matrix"]] == ["Elan"] and rb["funnel"][0]["count"] == 1 and rb["stuck"] == []
    )
    ra = data["ta"][0].get(url + "?stuck_days=30").data["competency"]
    assert len(ra["matrix"]) == 3 and ra["stuck_days"] == 30
    assert data["ta"][0].get(url + "?stuck_days=abc").data["competency"]["stuck_days"] == 7
    assert "SECRET-GOAL" not in str(r.data)
    # plain learner / other org refused
    assert data["l"]["Kavin"][0].get(url).status_code == 403
    oc, _ = user("other@else.in")
    other = oc.post("/api/orgs/", {"name": "Else", "kind": "school"}, format="json").data["slug"]
    assert oc.get(f"/api/orgs/{other}/teach/assignments/{a.id}/roleplay/").status_code == 404
    assert oc.get(url).status_code in (403, 404)


def test_concept_drilldown_ai_cached_and_charged(data):
    slug, a = data["slug"], data["a"]
    base = f"/api/orgs/{slug}/teach/assignments/{a.id}/roleplay/concepts/"
    oc = data["owner"][0]
    d = oc.get(base + "o1/").data
    assert d["concept"]["name"] == "Agree next step" and d["final"] == {"met": 0, "not_met": 4}
    assert {x["text"] for x in d["wrong"]} == {"Did not propose a meeting"} and d["insight"] is None
    o0 = oc.get(base + "o0/").data
    assert {x["text"] for x in o0["right"]} == {"Asked what worried her"} and {
        x["text"] for x in o0["wrong"]
    } == {"Interrupted the parent"}
    c0 = oc.get(base + "c0/").data
    assert c0["right"] == [{"text": "Shows real care", "learners": 1}] and c0["wrong"] == [
        {"text": "Sounds cold", "learners": 1}
    ]
    assert oc.get(base + "o9/").status_code == 404 and oc.get(base + "x1/").status_code == 404
    r = oc.post(base + "o1/")
    assert (
        r.status_code == 200
        and r.data["insight"]["got_wrong"]
        and r.data["insight"]["concept"] == "Agree next step"
    )
    assert TeachInsight.objects.filter(assignment=a, kind="rpc:o1").count() == 1
    assert UsageCounter.objects.get(user=data["owner"][1], metric="teach_ai").amount == 1
    assert oc.get(base + "o1/").data["insight"]["summary"]  # cached
    oc.post(base + "o1/")  # regenerate: still one cached row, charged again
    assert TeachInsight.objects.filter(assignment=a, kind="rpc:o1").count() == 1
    assert UsageCounter.objects.get(user=data["owner"][1], metric="teach_ai").amount == 2
    # 8-B teacher: own scope — nothing to analyse, and the owner's cached read-out isn't shown
    tb = data["tb"][0]
    assert tb.get(base + "o1/").data["insight"] is None
    assert tb.post(base + "o1/").data["code"] == "no_attempts"
    assert data["l"]["Kavin"][0].get(base + "o1/").status_code == 403


def test_export_includes_competency_tables_formula_safe(data):
    slug, a = data["slug"], data["a"]
    a.scenario.objectives = ["=cmd|' /C calc'!A0", "Agree next step"]
    a.scenario.save()
    oc = data["owner"][0]
    r = oc.get(f"/api/orgs/{slug}/teach/assignments/{a.id}/roleplay/?export=csv")
    body = r.content.decode()
    rows = list(csv.reader(io.StringIO(body)))
    assert rows[0][0] == "Learner"
    cells = [c for row in rows for c in row]
    assert not any(c.startswith(("=", "+", "@")) for c in cells)  # names, concept headers: all neutralised
    assert "'=HYPERLINK(evil)" in cells and "Objective: =cmd|' /C calc'!A0" in cells
    assert ["Stage", "Learners", "% of assigned"] in rows and ["passed", "1", "25%"] in rows
    assert any(r_[0] == "Kavin" and "many_attempts" in r_[1] for r_ in rows if len(r_) > 1)
    x = oc.get(f"/api/orgs/{slug}/teach/assignments/{a.id}/roleplay/?export=xlsx")
    z = zipfile.ZipFile(io.BytesIO(x.content))
    names = z.namelist()
    assert sum(1 for n in names if n.startswith("xl/worksheets/sheet")) == 4
    allxml = "".join(z.read(n).decode() for n in names if n.endswith(".xml"))
    assert "<f>" not in allxml  # no formulas anywhere
