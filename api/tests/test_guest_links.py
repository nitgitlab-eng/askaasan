"""Guest links: creator permissions, link rules (max uses / expiry / inactive), retargeting, guest-safe lessons,
claiming progress after sign-up, throttling, stats + CSV export, guest role-play caps."""

import csv
import io
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.guests.models import GuestLink, GuestVisitor
from apps.learning import activities
from apps.learning.models import (
    Activity,
    ActivityAttempt,
    Curriculum,
    Enrollment,
    Section,
    Subsection,
    UserSubsectionState,
)
from apps.orgs.models import Membership, Organization
from apps.roleplay.models import RolePlaySession, Scenario

pytestmark = pytest.mark.django_db
PW = "Guest#Links2026"


def client_for(email, **kw):
    u = User.objects.create_user(email, PW, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


QUIZ = {
    "type": "quiz",
    "title": "Pick",
    "prompt": "Which learns from data?",
    "options": ["Rule", "ML model", "Torch"],
    "correct": [1],
    "multiple": False,
    "explanation": "ML learns.",
}
OPEN = {
    "type": "open_input",
    "title": "Explain",
    "prompt": "Explain AI",
    "model_answer": "secret model answer",
    "rubric": ["r"],
}


def make_course(owner, title="Course", lessons=2, published=True):
    cur = Curriculum.objects.create(
        owner=owner,
        kind="authored",
        goal=title,
        title=title,
        status="ready",
        visibility="link",
        published_at=timezone.now() if published else None,
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="S1")
    for i in range(lessons):
        sub = Subsection.objects.create(
            section=sec, order=i, title=f"{title} L{i}", lesson_status="ready", explanation_md="text"
        )
        for j, act in enumerate((QUIZ, OPEN)):
            payload, key = activities.build(act, seed=sub.id * 100 + j)
            Activity.objects.create(
                subsection=sub,
                order=j,
                type=act["type"],
                title=act["title"],
                payload=payload,
                key=key,
                source=act,
            )
    return cur


@pytest.fixture
def creator():
    return client_for("author@guest.test", is_creator=True)


def new_link(c, course, **extra):
    r = c.post(
        "/api/guests/links/",
        {"label": "Open day", "target_kind": "course", "course_id": course.id, **extra},
        format="json",
    )
    assert r.status_code == 201, r.data
    return r.data


def start(slug, **body):
    g = APIClient()
    r = g.post(f"/api/guests/public/{slug}/start/", body, format="json")
    if r.status_code == 201:
        g.credentials(HTTP_X_GUEST_TOKEN=r.data["token"])
    return g, r


# ── Creator permissions ──────────────────────────────────────────────


def test_plain_learner_cannot_create_or_list(auth):
    c, _ = auth
    assert c.get("/api/guests/links/").status_code == 403
    assert (
        c.post(
            "/api/guests/links/", {"label": "x", "target_kind": "course", "course_id": 1}, format="json"
        ).status_code
        == 403
    )
    assert c.get("/api/guests/targets/").status_code == 403


def test_target_must_be_own_published_course(creator):
    c, u = creator
    other, ou = client_for("other@guest.test", is_creator=True)
    foreign = make_course(ou, "Foreign")
    draft = make_course(u, "Draft", published=False)
    for cid in (foreign.id, draft.id):
        r = c.post(
            "/api/guests/links/", {"label": "x", "target_kind": "course", "course_id": cid}, format="json"
        )
        assert r.status_code == 400 and r.data["code"] == "bad_course"
    link = new_link(c, make_course(u))
    assert other.get(f"/api/guests/links/{link['id']}/").status_code == 404
    assert (
        other.patch(f"/api/guests/links/{link['id']}/", {"active": False}, format="json").status_code == 404
    )
    assert other.get(f"/api/guests/links/{link['id']}/export.csv").status_code == 404
    assert other.get(f"/api/guests/links/{link['id']}/qr/").status_code == 404


def test_org_manager_sees_org_links_but_learner_does_not(creator):
    c, u = creator
    org = Organization.objects.create(name="Acme", slug="acme")
    Membership.objects.create(org=org, user=u, role="owner")
    link = new_link(c, make_course(u), org="acme")
    mgr, mu = client_for("mgr@guest.test")
    Membership.objects.create(org=org, user=mu, role="manager")
    assert any(x["id"] == link["id"] for x in mgr.get("/api/guests/links/?org=acme").data)
    learner, lu = client_for("learner@guest.test")
    Membership.objects.create(org=org, user=lu, role="learner")
    assert learner.get("/api/guests/links/").status_code == 403
    outsider, _ = client_for("out@guest.test", is_creator=True)
    r = outsider.post(
        "/api/guests/links/",
        {"label": "x", "target_kind": "course", "course_id": 1, "org": "acme"},
        format="json",
    )
    assert r.status_code in (400, 404)


def test_slug_custom_unique_and_validated(creator):
    c, u = creator
    cur = make_course(u)
    new_link(c, cur, slug="open-day")
    r = c.post(
        "/api/guests/links/",
        {"label": "x", "target_kind": "course", "course_id": cur.id, "slug": "open-day"},
        format="json",
    )
    assert r.status_code == 409
    r = c.post(
        "/api/guests/links/",
        {"label": "x", "target_kind": "course", "course_id": cur.id, "slug": "Bad Slug!"},
        format="json",
    )
    assert r.status_code == 400


# ── Link rules ───────────────────────────────────────────────────────


def test_max_uses_enforced(creator):
    c, u = creator
    link = new_link(c, make_course(u), max_uses=2)
    assert start(link["slug"])[1].status_code == 201
    assert start(link["slug"])[1].status_code == 201
    _, r = start(link["slug"])
    assert r.status_code == 410 and r.data["code"] == "link_full"
    assert APIClient().get(f"/api/guests/public/{link['slug']}/").data["state"] == "full"


def test_expired_and_inactive_refused(creator):
    c, u = creator
    link = new_link(c, make_course(u))
    g, r = start(link["slug"])
    lesson_id = APIClient().get(f"/api/guests/public/{link['slug']}/").data["target"]["lessons"][0]["id"]
    c.patch(f"/api/guests/links/{link['id']}/", {"active": False}, format="json")
    assert start(link["slug"])[1].data["code"] == "link_inactive"
    assert (
        g.get(f"/api/guests/public/{link['slug']}/lesson/{lesson_id}/").status_code == 410
    )  # existing guests stop too
    c.patch(
        f"/api/guests/links/{link['id']}/",
        {"active": True, "expires_at": (timezone.now() - timedelta(minutes=1)).isoformat()},
        format="json",
    )
    assert start(link["slug"])[1].data["code"] == "link_expired"
    assert g.get(f"/api/guests/public/{link['slug']}/lesson/{lesson_id}/").status_code == 410


def test_unknown_slug_404():
    assert APIClient().get("/api/guests/public/nope-nope/").status_code == 404


def test_retarget_keeps_slug_and_moves_guests(creator):
    c, u = creator
    a, b = make_course(u, "Alpha"), make_course(u, "Beta")
    link = new_link(c, a, slug="try-us")
    g, _ = start("try-us")
    old_lesson = Subsection.objects.filter(section__curriculum=a).first()
    assert g.get(f"/api/guests/public/try-us/lesson/{old_lesson.id}/").status_code == 200
    r = c.patch(f"/api/guests/links/{link['id']}/", {"course_id": b.id}, format="json")
    assert r.status_code == 200 and r.data["slug"] == "try-us" and r.data["course"]["id"] == b.id
    land = APIClient().get("/api/guests/public/try-us/").data
    assert land["target"]["title"] == "Beta"
    assert g.get(f"/api/guests/public/try-us/lesson/{old_lesson.id}/").status_code == 404
    new_lesson = Subsection.objects.filter(section__curriculum=b).first()
    assert g.get(f"/api/guests/public/try-us/lesson/{new_lesson.id}/").status_code == 200


# ── Guest-safe lessons ───────────────────────────────────────────────


def test_lessons_need_guest_token_and_never_leak_keys(creator):
    c, u = creator
    cur = make_course(u)
    link = new_link(c, cur)
    sub = Subsection.objects.filter(section__curriculum=cur).first()
    assert APIClient().get(f"/api/guests/public/{link['slug']}/lesson/{sub.id}/").status_code == 401
    g, _ = start(link["slug"])
    d = g.get(f"/api/guests/public/{link['slug']}/lesson/{sub.id}/").data
    body = str(d)
    assert (
        "secret model answer" not in body
        and "'correct'" not in body
        and "key" not in {k for a in d["activities"] for k in a}
    )
    assert [a["locked"] for a in d["activities"]] == [False, True]


def test_attempts_only_for_target_course(creator):
    c, u = creator
    mine, other_course = (
        make_course(u, "Mine"),
        make_course(client_for("x@guest.test", is_creator=True)[1], "Other"),
    )
    link = new_link(c, mine)
    g, _ = start(link["slug"])
    foreign = Activity.objects.filter(subsection__section__curriculum=other_course, type="quiz").first()
    assert (
        g.post(
            f"/api/guests/public/{link['slug']}/attempt/{foreign.id}/",
            {"answer": {"selected": [1]}},
            format="json",
        ).status_code
        == 404
    )
    foreign_sub = foreign.subsection_id
    assert g.get(f"/api/guests/public/{link['slug']}/lesson/{foreign_sub}/").status_code == 404
    quiz = Activity.objects.filter(subsection__section__curriculum=mine, type="quiz").first()
    opn = Activity.objects.filter(subsection__section__curriculum=mine, type="open_input").first()
    assert (
        g.post(
            f"/api/guests/public/{link['slug']}/attempt/{opn.id}/", {"answer": {"text": "hi"}}, format="json"
        ).status_code
        == 403
    )
    r = g.post(
        f"/api/guests/public/{link['slug']}/attempt/{quiz.id}/", {"answer": {"selected": [1]}}, format="json"
    )
    assert r.status_code == 200 and r.data["correct"] is True
    # someone else's token can't see this guest's answers
    g2, _ = start(link["slug"])
    d = g2.get(f"/api/guests/public/{link['slug']}/lesson/{quiz.subsection_id}/").data
    assert all(a["attempt"] is None for a in d["activities"])


def test_roleplay_link_has_no_lessons(creator):
    c, u = creator
    sc = Scenario.objects.create(
        owner=u,
        title="Pitch",
        summary="s",
        learner_role="student",
        character={"name": "A", "persona": "p", "goal": "g", "style": "s"},
        setting="x",
        objectives=["a", "b"],
        competencies=[{"name": "C1", "description": "d"}, {"name": "C2", "description": "d"}],
        opening_line="Hello!",
    )
    r = c.post(
        "/api/guests/links/", {"label": "rp", "target_kind": "roleplay", "scenario_id": sc.id}, format="json"
    )
    assert r.status_code == 201
    q = Activity.objects.filter(subsection__section__curriculum=make_course(u)).first()
    g, _ = start(r.data["slug"])
    assert (
        g.post(
            f"/api/guests/public/{r.data['slug']}/attempt/{q.id}/",
            {"answer": {"selected": [1]}},
            format="json",
        ).status_code
        == 404
    )


# ── Collect email + magic link ───────────────────────────────────────


def test_collect_email_and_magic_link_resume(creator, mailoutbox):
    c, u = creator
    link = new_link(c, make_course(u), collect_email=True)
    slug = link["slug"]
    assert start(slug)[1].status_code == 400
    g, r = start(slug, name="Priya", email="Priya@Example.com")
    assert r.status_code == 201
    # same email again: the same response as a brand-new email (no enumeration) but a fresh, empty visitor;
    # the address owner gets a fixed-text resume email (nothing the stranger typed is echoed)
    g2, r2 = start(slug, name="Mallory <a href=x>", email="priya@example.com")
    _, r3 = start(slug, name="Nobody", email="new@example.com")
    assert r2.status_code == r3.status_code == 201 and set(r2.data) == set(r3.data) == {"token", "me"}
    assert r2.data["me"]["lessons_done"] == [] and r2.data["token"] != r.data["token"]
    assert len(mailoutbox) == 1 and mailoutbox[0].to == ["priya@example.com"]
    assert "Mallory" not in mailoutbox[0].body and "Priya" not in mailoutbox[0].body
    magic = mailoutbox[0].body.split("?m=")[1].split()[0]
    d = APIClient().post(f"/api/guests/public/{slug}/resume/", {"magic": magic}, format="json")
    assert d.status_code == 200 and d.data["me"]["name"] == "Priya"
    # single use: the same magic link can't be replayed, and the old device token stops working
    assert (
        APIClient().post(f"/api/guests/public/{slug}/resume/", {"magic": magic}, format="json").status_code
        == 400
    )
    assert g.get(f"/api/guests/public/{slug}/summary/").status_code == 401
    assert (
        APIClient()
        .post(f"/api/guests/public/{slug}/resume/", {"magic": magic + "x"}, format="json")
        .status_code
        == 400
    )
    # the magic link is bound to its own link
    other = new_link(c, make_course(u, "Other"))
    assert (
        APIClient()
        .post(f"/api/guests/public/{other['slug']}/resume/", {"magic": magic}, format="json")
        .status_code
        == 400
    )
    assert c.get(f"/api/guests/links/{link['id']}/stats/").data["emails"] == 3


# ── Claim on sign-up ─────────────────────────────────────────────────


def test_guest_progress_attaches_on_signup(creator):
    c, u = creator
    cur = make_course(u)
    link = new_link(c, cur)
    slug = link["slug"]
    g, r = start(slug, name="Arun")
    token = r.data["token"]
    quiz = Activity.objects.filter(subsection__section__curriculum=cur, type="quiz").first()
    g.post(f"/api/guests/public/{slug}/attempt/{quiz.id}/", {"answer": {"selected": [1]}}, format="json")
    g.post(f"/api/guests/public/{slug}/lesson/{quiz.subsection_id}/done/")
    g.post(f"/api/guests/public/{slug}/finish/")
    new = APIClient()
    reg = new.post("/api/users/register/", {"email": "arun@guest.test", "password": PW}, format="json")
    assert reg.status_code == 201, reg.data
    new.credentials(HTTP_AUTHORIZATION=f"Bearer {reg.data['access']}")
    assert new.post("/api/guests/claim/", {"slug": slug}, format="json").status_code == 404  # token required
    new.credentials(HTTP_AUTHORIZATION=f"Bearer {reg.data['access']}", HTTP_X_GUEST_TOKEN=token)
    res = new.post("/api/guests/claim/", {"slug": slug}, format="json")
    assert (
        res.status_code == 200
        and res.data["course_id"] == cur.id
        and res.data["attempts"] == 1
        and res.data["lessons"] == 1
    )
    user = User.objects.get(email="arun@guest.test")
    assert Enrollment.objects.filter(user=user, curriculum=cur).exists()
    assert ActivityAttempt.objects.filter(user=user, activity=quiz).count() == 1
    # never marked completed by a claim: completion (and certificates) follow the normal learner path
    assert (
        UserSubsectionState.objects.get(user=user, subsection_id=quiz.subsection_id).status == "in_progress"
    )
    assert not UserSubsectionState.objects.filter(user=user, status="completed").exists()
    assert new.post("/api/guests/claim/", {"slug": slug}, format="json").data["attempts"] == 0  # idempotent
    other, _ = client_for("thief@guest.test")
    other.credentials(HTTP_X_GUEST_TOKEN=token)
    assert other.post("/api/guests/claim/", {"slug": slug}, format="json").status_code == 409
    s = c.get(f"/api/guests/links/{link['id']}/stats/").data
    assert (s["starts"], s["completions"], s["signups"], s["conversion"]) == (1, 1, 1, 1.0)
    assert s["opens"] == 0


# ── Throttling ───────────────────────────────────────────────────────


def test_public_start_is_throttled(creator):
    c, u = creator
    link = new_link(c, make_course(u))
    codes = [
        APIClient().post(f"/api/guests/public/{link['slug']}/start/", {}, format="json").status_code
        for _ in range(22)
    ]
    assert codes[0] == 201 and codes[-1] == 429


def test_public_reads_are_throttled(creator, settings):
    from apps.guests.public import ReadThrottle

    c, u = creator
    link = new_link(c, make_course(u))
    old = ReadThrottle.rate
    ReadThrottle.rate = "3/hour"
    try:
        codes = [APIClient().get(f"/api/guests/public/{link['slug']}/").status_code for _ in range(5)]
    finally:
        ReadThrottle.rate = old
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429


def test_opens_counted_once_per_ip(creator):
    c, u = creator
    link = new_link(c, make_course(u))
    for _ in range(3):
        APIClient().get(f"/api/guests/public/{link['slug']}/")
    assert GuestLink.objects.get(pk=link["id"]).opens == 1


# ── Stats export ─────────────────────────────────────────────────────


def test_csv_export_is_formula_safe(creator):
    c, u = creator
    link = new_link(c, make_course(u), collect_email=True)
    start(link["slug"], name='=HYPERLINK("http://evil")', email="a@b.co")
    start(link["slug"], name="@SUM(1)", email="c@d.co")
    r = c.get(f"/api/guests/links/{link['id']}/export.csv")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.content.decode())))
    assert rows[0][0] == "name"
    names = [row[0] for row in rows[1:]]
    assert all(n.startswith("'") for n in names)


def test_qr_download(creator):
    c, u = creator
    link = new_link(c, make_course(u))
    svg = c.get(f"/api/guests/links/{link['id']}/qr/")
    assert (
        svg.status_code == 200 and svg["Content-Type"] == "image/svg+xml" and svg.content.startswith(b"<svg")
    )
    png = c.get(f"/api/guests/links/{link['id']}/qr/?as=png")
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"


# ── Guest role-play ──────────────────────────────────────────────────


@pytest.fixture
def rp_link(creator):
    c, u = creator
    sc = Scenario.objects.create(
        owner=u,
        title="Pitch",
        summary="s",
        learner_role="student",
        character={"name": "A", "persona": "p", "goal": "g", "style": "s"},
        setting="x",
        objectives=["State the problem", "Explain the solution"],
        competencies=[{"name": "Simplicity", "description": "d"}, {"name": "Empathy", "description": "d"}],
        opening_line="So, what's your idea?",
        max_turns=10,
    )
    r = c.post(
        "/api/guests/links/", {"label": "rp", "target_kind": "roleplay", "scenario_id": sc.id}, format="json"
    )
    return r.data["slug"]


def test_guest_roleplay_turn_cap_and_eval(rp_link, settings):
    settings.GUEST_ROLEPLAY_TURNS = 3
    g, _ = start(rp_link)
    s = g.post(f"/api/guests/public/{rp_link}/role-play/", {}, format="json").data
    assert s["turns"][0]["text"] == "So, what's your idea?" and s["turns_left"] == 3
    assert g.post(f"/api/guests/public/{rp_link}/role-play/end/").data["code"] == "too_short"
    for i in range(3):
        r = g.post(
            f"/api/guests/public/{rp_link}/role-play/say/",
            {"text": f"Banks never ask for OTP Paati {i}"},
            format="json",
        )
        assert r.status_code == 200 and r.data["turns"][-1]["role"] == "character"
    r = g.post(f"/api/guests/public/{rp_link}/role-play/say/", {"text": "one more"}, format="json")
    assert r.status_code == 409 and r.data["code"] == "turn_limit"
    end = g.post(f"/api/guests/public/{rp_link}/role-play/end/")
    assert (
        end.status_code == 200
        and end.data["status"] == "completed"
        and 0 <= end.data["result"]["overall"] <= 100
    )


def test_guest_roleplay_daily_ai_caps(rp_link, settings):
    settings.GUEST_AI_PER_IP_DAY = 2
    g, _ = start(rp_link)
    g.post(f"/api/guests/public/{rp_link}/role-play/", {}, format="json")
    codes = [
        g.post(
            f"/api/guests/public/{rp_link}/role-play/say/", {"text": "hi there"}, format="json"
        ).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]
    settings.GUEST_AI_PER_IP_DAY = 100
    settings.GUEST_AI_PER_LINK_DAY = 2  # link already used 2 today
    r = g.post(f"/api/guests/public/{rp_link}/role-play/say/", {"text": "hi"}, format="json")
    assert r.status_code == 429 and r.data["code"] == "guest_ai_limit"


def test_guest_roleplay_claimed_into_account(rp_link):
    g, r = start(rp_link)
    token = r.data["token"]
    g.post(f"/api/guests/public/{rp_link}/role-play/", {}, format="json")
    for t in ("Banks never ask for OTP Paati", "Please call the bank"):
        g.post(f"/api/guests/public/{rp_link}/role-play/say/", {"text": t}, format="json")
    g.post(f"/api/guests/public/{rp_link}/role-play/end/")
    c, u = client_for("rp@guest.test")
    c.credentials(HTTP_X_GUEST_TOKEN=token)
    assert c.post("/api/guests/claim/", {"slug": rp_link}, format="json").data["roleplays"] == 1
    s = RolePlaySession.objects.get(user=u)
    assert s.status == "completed" and s.turns.count() == 5
    assert GuestVisitor.objects.get().claimed_by == u


# ── Security review regressions ──────────────────────────────────────


def _unit_scoped_manager(org, email):
    from apps.orgs.models import SubUnit, UnitAdmin

    c, u = client_for(email)
    m = Membership.objects.create(org=org, user=u, role="manager", unit_scoped=True)
    UnitAdmin.objects.create(unit=SubUnit.objects.create(org=org, name="Primary"), membership=m)
    return c, u


def test_unit_scoped_manager_cannot_see_or_touch_org_links(creator):
    c, u = creator
    org = Organization.objects.create(name="Acme", slug="acme")
    Membership.objects.create(org=org, user=u, role="owner")
    link = new_link(c, make_course(u), org="acme")
    unit_c, _ = _unit_scoped_manager(org, "unit@guest.test")
    assert unit_c.get("/api/guests/links/").status_code == 403
    for call in (
        lambda: unit_c.get(f"/api/guests/links/{link['id']}/"),
        lambda: unit_c.get(f"/api/guests/links/{link['id']}/export.csv"),
        lambda: unit_c.patch(f"/api/guests/links/{link['id']}/", {"active": False}, format="json"),
        lambda: unit_c.delete(f"/api/guests/links/{link['id']}/"),
    ):
        assert call().status_code in (403, 404)
    assert GuestLink.objects.get(pk=link["id"]).active


def test_only_owner_or_org_admin_edits_org_links(creator):
    c, u = creator
    org = Organization.objects.create(name="Acme", slug="acme")
    Membership.objects.create(org=org, user=u, role="manager")
    link = new_link(c, make_course(u), org="acme")
    mgr, mu = client_for("mgr2@guest.test")
    Membership.objects.create(org=org, user=mu, role="manager")
    assert mgr.get(f"/api/guests/links/{link['id']}/").status_code == 200  # can read
    assert mgr.patch(f"/api/guests/links/{link['id']}/", {"active": False}, format="json").status_code == 403
    assert mgr.delete(f"/api/guests/links/{link['id']}/").status_code == 403
    adm, au = client_for("admin@guest.test")
    Membership.objects.create(org=org, user=au, role="admin")
    assert adm.patch(f"/api/guests/links/{link['id']}/", {"active": False}, format="json").status_code == 200


def test_lesson_done_needs_every_auto_graded_answer(creator):
    c, u = creator
    cur = make_course(u)
    link = new_link(c, cur)
    g, _ = start(link["slug"])
    quiz = Activity.objects.filter(subsection__section__curriculum=cur, type="quiz").first()
    assert g.post(f"/api/guests/public/{link['slug']}/lesson/{quiz.subsection_id}/done/").status_code == 409
    g.post(f"/api/guests/public/{link['slug']}/finish/")
    assert (
        GuestVisitor.objects.get().completed_at is None
    )  # clicking Finish without doing anything isn't a completion
    g.post(
        f"/api/guests/public/{link['slug']}/attempt/{quiz.id}/", {"answer": {"selected": [0]}}, format="json"
    )
    assert g.post(f"/api/guests/public/{link['slug']}/lesson/{quiz.subsection_id}/done/").status_code == 200


def test_inactive_or_expired_link_blocks_done_finish_summary_claim(creator):
    c, u = creator
    cur = make_course(u)
    link = new_link(c, cur)
    slug = link["slug"]
    g, r = start(slug)
    quiz = Activity.objects.filter(subsection__section__curriculum=cur, type="quiz").first()
    g.post(f"/api/guests/public/{slug}/attempt/{quiz.id}/", {"answer": {"selected": [1]}}, format="json")
    c.patch(
        f"/api/guests/links/{link['id']}/",
        {"expires_at": (timezone.now() - timedelta(minutes=1)).isoformat()},
        format="json",
    )
    assert g.post(f"/api/guests/public/{slug}/lesson/{quiz.subsection_id}/done/").status_code == 410
    assert g.post(f"/api/guests/public/{slug}/finish/").status_code == 410
    assert g.get(f"/api/guests/public/{slug}/summary/").status_code == 410
    land = APIClient().get(f"/api/guests/public/{slug}/").data
    assert (
        land["state"] == "expired" and land["target"] is None and land["label"] == ""
    )  # no course title / lessons
    nc, nu = client_for("late@guest.test")
    nc.credentials(HTTP_X_GUEST_TOKEN=r.data["token"])
    assert nc.post("/api/guests/claim/", {"slug": slug}, format="json").status_code == 410
    assert (
        not Enrollment.objects.filter(user=nu).exists()
        and not ActivityAttempt.objects.filter(user=nu).exists()
    )


def test_magic_link_emails_capped_per_recipient(creator, mailoutbox):
    c, u = creator
    link = new_link(c, make_course(u), collect_email=True)
    start(link["slug"], name="Victim", email="victim@example.com")
    for i in range(
        6
    ):  # strangers keep typing the victim's address (from different links/IPs it's still capped)
        start(link["slug"], name=f"x{i}", email="victim@example.com")
    assert len(mailoutbox) == 3


def test_ipv6_bucketed_by_64():
    from apps.guests.services import ip_bucket

    assert ip_bucket("2001:db8:1:2:aaaa::1") == ip_bucket("2001:db8:1:2:bbbb::9") == "2001:db8:1:2::/64"
    assert ip_bucket("2001:db8:1:3::1") != ip_bucket("2001:db8:1:2::1")
    assert ip_bucket("203.0.113.5") == "203.0.113.5"


def test_ipv6_neighbours_share_a_throttle(creator):
    c, u = creator
    link = new_link(c, make_course(u))
    codes = [
        APIClient(REMOTE_ADDR=f"2001:db8:1:2::{i + 1:x}")
        .post(f"/api/guests/public/{link['slug']}/start/", {}, format="json")
        .status_code
        for i in range(22)
    ]
    assert codes[0] == 201 and codes[-1] == 429


def test_guest_ai_owner_and_global_caps(rp_link, settings):
    g, _ = start(rp_link)
    g.post(f"/api/guests/public/{rp_link}/role-play/", {}, format="json")
    settings.GUEST_AI_PER_OWNER_DAY = 1
    assert (
        g.post(f"/api/guests/public/{rp_link}/role-play/say/", {"text": "hi"}, format="json").status_code
        == 200
    )
    assert (
        g.post(f"/api/guests/public/{rp_link}/role-play/say/", {"text": "hi"}, format="json").data["code"]
        == "guest_ai_limit"
    )
    settings.GUEST_AI_PER_OWNER_DAY = 100
    settings.GUEST_AI_GLOBAL_DAY = 1
    assert (
        g.post(f"/api/guests/public/{rp_link}/role-play/say/", {"text": "hi"}, format="json").status_code
        == 429
    )
