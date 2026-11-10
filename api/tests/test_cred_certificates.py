"""Credentials: auto-issue on course completion (exactly once), public verification (allowed fields only; 404 when
revoked/hidden), PDF (magic bytes, escaped titles), org-manager issuing with evidence, share-your-progress (AI, charged)."""

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.credentials.models import Certificate
from apps.credentials.pdf import safe
from apps.credentials.pdf_fonts import fonts
from apps.game.models import Notification
from apps.learning.models import (
    Activity,
    ActivityAttempt,
    Curriculum,
    Enrollment,
    Section,
    Subsection,
    UserSubsectionState,
)
from apps.orgs.models import Assignment, Membership, Organization, Survey, SurveyResponse
from apps.roleplay.models import RolePlaySession, Scenario

pytestmark = pytest.mark.django_db
PW = "Cred#2026passwd"
EVIL = '<img src="http://evil.example/x.png"/><b>Hacked & co</b>'


def client_for(email, name=""):
    u = User.objects.create_user(email, PW)
    if name:
        u.profile.display_name = name
        u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def course(owner, title="Excel basics", n=2, archived=1, approved=True, learner=None):
    """A published course by `owner` with one graded lesson activity per lesson; `learner` gets enrolled."""
    cur = Curriculum.objects.create(
        owner=owner,
        goal="Learn Excel",
        title=title,
        status="ready",
        kind="authored",
        visibility="catalog",
        published_at=timezone.now(),
        catalog_status="approved" if approved else "none",
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="Start")
    subs = [
        Subsection.objects.create(section=sec, order=i, title=f"L{i}", lesson_status="ready")
        for i in range(n)
    ]
    for s in subs:
        Activity.objects.create(
            subsection=s, order=0, type="quiz", kind="lesson", title="Q", payload={}, key={}
        )
    for i in range(archived):  # archived lessons don't count
        Subsection.objects.create(section=sec, order=n + i, title="Old", archived=True)
    if learner:
        Enrollment.objects.create(user=learner, curriculum=cur)
    return cur, subs


def complete(c, subs, score=1.0, attempt=True):
    from apps.accounts.models import User as U

    u = U.objects.get(pk=c.handler._force_user.pk)
    for s in subs:
        if attempt:
            ActivityAttempt.objects.create(
                user=u, activity=s.activities.first(), answer={}, score=score, correct=score >= 0.6
            )
        assert c.post(f"/api/learn/subsections/{s.id}/complete/").status_code == 200


@pytest.fixture
def learner():
    return client_for("kavya@example.com", "Kavya R")


@pytest.fixture
def author():
    return client_for("author@example.com", "Ravi Teacher")[1]


def test_course_certificate_issued_exactly_once(learner, author):
    c, u = learner
    cur, subs = course(author, learner=u)
    complete(c, subs[:1])
    assert not Certificate.objects.exists()  # not done yet
    complete(c, subs[1:])
    complete(c, subs)  # redoing lessons doesn't issue again
    UserSubsectionState.objects.filter(user=u).first().save()
    cert = Certificate.objects.get()
    assert (cert.user, cert.kind, cert.title, cert.issuer_name, cert.learner_name, cert.org) == (
        u,
        "course",
        "Excel basics",
        "Aasan",
        "Kavya R",
        None,
    )
    assert (cert.author_name, cert.issuer_type) == ("Ravi Teacher", "aasan")
    assert len(cert.code) >= 20 and Notification.objects.filter(user=u, kind="certificate").count() == 1
    mine = c.get("/api/credentials/").data
    assert len(mine) == 1 and mine[0]["verify_url"].endswith(f"/verify/{cert.code}")
    # revoked stays revoked: completing again never re-issues
    c.post(f"/api/credentials/{cert.id}/revoke/")
    complete(c, subs)
    assert Certificate.objects.count() == 1


def test_verification_shows_only_allowed_fields_and_hides(learner, author):
    c, u = learner
    cur, subs = course(author, title="Python for data", learner=u)
    complete(c, subs)
    cert = Certificate.objects.get()
    anon = APIClient()
    v = anon.get(f"/api/credentials/verify/{cert.code}/")
    assert v.status_code == 200
    assert set(v.data) == {
        "code",
        "learner",
        "title",
        "kind",
        "issuer",
        "issued_by_type",
        "org",
        "author",
        "issued_at",
        "verified",
        "verify_url",
    }
    assert v.data["learner"] == "Kavya R" and v.data["verified"] is True and u.email not in str(v.data)
    assert (v.data["issued_by_type"], v.data["org"], v.data["author"]) == ("aasan", None, "Ravi Teacher")
    assert anon.get("/api/credentials/verify/not-a-real-code-but-long-enough/").status_code == 404
    assert anon.get("/api/credentials/verify/x/").status_code == 404
    # hide → 404, show again → 200
    assert c.patch(f"/api/credentials/{cert.id}/", {"hidden": True}, format="json").data["hidden"] is True
    assert anon.get(f"/api/credentials/verify/{cert.code}/").status_code == 404
    c.patch(f"/api/credentials/{cert.id}/", {"hidden": False}, format="json")
    assert anon.get(f"/api/credentials/verify/{cert.code}/").status_code == 200
    # someone else can't hide, revoke or download it
    other, _ = client_for("x@example.com")
    assert other.patch(f"/api/credentials/{cert.id}/", {"hidden": True}, format="json").status_code == 404
    assert other.post(f"/api/credentials/{cert.id}/revoke/").status_code == 404
    assert other.get(f"/api/credentials/{cert.id}/pdf/").status_code == 404
    # revoke is permanent
    assert c.post(f"/api/credentials/{cert.id}/revoke/").data["revoked"] is True
    c.patch(f"/api/credentials/{cert.id}/", {"hidden": False}, format="json")
    gone = anon.get(f"/api/credentials/verify/{cert.code}/")
    assert gone.status_code == 410 and set(gone.data) == {"code", "revoked_at"}  # withdrawn, and nothing else
    assert c.get(f"/api/credentials/{cert.id}/pdf/").status_code == 404


def test_display_name_never_falls_back_to_email(author):
    c, u = client_for("private.person@example.com")
    cur, subs = course(author, learner=u)
    complete(c, subs)
    assert Certificate.objects.get().learner_name == "Aasan learner"


def test_pdf_magic_bytes_and_escaped_title(learner, author):
    c, u = learner
    cur, subs = course(author, title=EVIL, learner=u)
    complete(c, subs)
    cert = Certificate.objects.get()
    r = c.get(f"/api/credentials/{cert.id}/pdf/")
    assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and r.content[:5] == b"%PDF-"
    assert safe(EVIL).startswith("&lt;img") and "<" not in safe(EVIL)
    if not fonts():  # no Indic glyphs in built-in fonts: replaced, never crashes
        assert safe("தமிழ் name") == "????? name"
    else:  # Noto fonts installed: Tamil kept
        assert "தமிழ்" in safe("தமிழ் name")


@pytest.fixture
def school():
    org = Organization.objects.create(
        name="Vidya School", slug="vidya", display_name="Vidya Matric", kind="school"
    )
    mgr, mu = client_for("teacher@vidya.in", "Meena")
    Membership.objects.create(org=org, user=mu, role="manager")
    kid, ku = client_for("kid@vidya.in", "Arun")
    mk = Membership.objects.create(org=org, user=ku, role="learner")
    return org, (mgr, mu), (kid, ku, mk)


def test_manager_issues_with_evidence_only(school):
    org, (mgr, mu), (kid, ku, mk) = school
    cur, subs = course(mu, title="Safety training", learner=ku, approved=False)
    Assignment.objects.create(org=org, curriculum=cur)
    sc = Scenario.objects.create(
        title="Angry customer",
        summary="s",
        learner_role="agent",
        character={},
        setting="shop",
        opening_line="Hi",
    )
    Assignment.objects.create(org=org, scenario=sc)
    url = "/api/credentials/orgs/vidya/"
    assert mgr.get(f"{url}eligible/{mk.id}/").data == {"course": [], "scenario": [], "test": []}
    assert (
        mgr.post(url, {"member_id": mk.id, "kind": "course", "id": cur.id}, format="json").status_code == 403
    )  # not completed
    complete(kid, subs)
    RolePlaySession.objects.create(user=ku, scenario=sc, status="completed")
    s = Survey.objects.create(
        org=org,
        title="Fire test",
        kind="test",
        anonymous=False,
        status="open",
        questions=[
            {
                "id": "q1",
                "type": "choice",
                "text": "Exit?",
                "options": ["a", "b"],
                "correct": "a",
                "points": 1,
            }
        ],
    )
    SurveyResponse.objects.create(
        survey=s, respondent_key="k", user=ku, answers={"q1": "a"}, score=1, max_score=1, passed=True
    )
    el = mgr.get(f"{url}eligible/{mk.id}/").data
    assert (
        [x["id"] for x in el["course"]] == [cur.id]
        and [x["id"] for x in el["scenario"]] == [sc.id]
        and [x["id"] for x in el["test"]] == [s.id]
    )
    r = mgr.post(url, {"member_id": mk.id, "kind": "test", "id": s.id}, format="json")
    assert r.status_code == 201
    again = mgr.post(url, {"member_id": mk.id, "kind": "test", "id": s.id}, format="json")
    assert again.status_code == 200 and again.data["id"] == r.data["id"]
    assert (
        mgr.post(url, {"member_id": mk.id, "kind": "course", "id": cur.id}, format="json").status_code == 200
    )  # already auto-issued
    test_cert = Certificate.objects.get(kind="test")
    assert (
        test_cert.issuer_name == "Vidya Matric"
        and test_cert.detail == {"pct": 100}
        and test_cert.issued_by == mu
    )
    assert (
        Certificate.objects.filter(user=ku, kind="course").count() == 1
    )  # auto-issued by the assigning school; manager issue is idempotent
    pub = APIClient().get(f"/api/credentials/verify/{test_cert.code}/").data
    assert (pub["issuer"], pub["issued_by_type"], pub["org"]) == ("Vidya Matric", "organisation", "vidya")
    # learners, outsiders and other orgs are refused
    assert kid.post(url, {"member_id": mk.id, "kind": "test", "id": s.id}, format="json").status_code == 403
    assert kid.get(f"{url}eligible/{mk.id}/").status_code == 403
    out, ou = client_for("other@else.in")
    other = Organization.objects.create(name="Else", slug="else")
    Membership.objects.create(org=other, user=ou, role="owner")
    assert out.get(f"{url}").status_code == 404
    assert (
        out.get(f"/api/credentials/orgs/else/eligible/{mk.id}/").status_code == 404
    )  # member of another org
    assert out.post(f"/api/credentials/orgs/else/{test_cert.id}/revoke/").status_code == 404
    assert mgr.post(f"{url}{test_cert.id}/revoke/").data["revoked"] is True


def test_anonymous_tests_are_not_certifiable(school):
    org, (mgr, _), (kid, ku, mk) = school
    s = Survey.objects.create(
        org=org, title="Anon quiz", kind="test", anonymous=True, status="open", questions=[]
    )
    SurveyResponse.objects.create(
        survey=s, respondent_key="k", user=ku, answers={}, score=1, max_score=1, passed=True
    )
    assert (
        mgr.post(
            "/api/credentials/orgs/vidya/", {"member_id": mk.id, "kind": "test", "id": s.id}, format="json"
        ).status_code
        == 403
    )


def test_share_progress_from_review_and_certificate(learner, author):
    c, u = learner
    cur, subs = course(author, title="Excel basics", learner=u)
    complete(c, subs)
    cert = Certificate.objects.get()
    f = c.get("/api/credentials/share/facts/?source=review").data
    assert (
        f["kind"] == "review"
        and f["stats"]["lessons"] == 2
        and f["certificates"] == ["Excel basics"]
        and u.email not in str(f)
    )
    r = c.post("/api/credentials/share/", {"source": "review", "format": "linkedin"}, format="json")
    assert (
        r.status_code == 200
        and r.data["text"]
        and r.data["hashtags"] == ["Learning", "Aasan", "badtag", "Growth"]
    )
    m = c.post(
        "/api/credentials/share/",
        {"source": "certificate", "certificate_id": cert.id, "format": "manager"},
        format="json",
    )
    assert (
        m.status_code == 200 and m.data["hashtags"] == [] and m.data["facts"]["certificate"] == "Excel basics"
    )
    assert (
        c.post("/api/credentials/share/", {"source": "review", "format": "tweet"}, format="json").status_code
        == 400
    )
    other, _ = client_for("x@example.com")
    assert (
        other.post(
            "/api/credentials/share/",
            {"source": "certificate", "certificate_id": cert.id, "format": "manager"},
            format="json",
        ).status_code
        == 404
    )
    assert (
        APIClient()
        .post("/api/credentials/share/", {"source": "review", "format": "manager"}, format="json")
        .status_code
        == 401
    )


def test_share_is_charged(learner, monkeypatch):
    from apps.providers import services

    c, _ = learner
    monkeypatch.setattr(
        services, "charge", lambda *a, **k: (_ for _ in ()).throw(services.BudgetExceeded("ai_grades"))
    )
    r = c.post("/api/credentials/share/", {"source": "review", "format": "manager"}, format="json")
    assert r.status_code == 429 and r.data["code"] == "ai_budget_exceeded"


# ── Security review regressions ──────────────────────────────────────


def test_no_self_minted_certificates(learner):
    """Own/self-authored courses never earn a certificate, even if approved."""
    c, u = learner
    cur, subs = course(u, title="Google Certified Cloud Architect")
    complete(c, subs)
    assert not Certificate.objects.exists()


def test_unapproved_unassigned_course_gets_no_certificate(learner, author):
    c, u = learner
    cur, subs = course(author, title="Google Certified Cloud Architect", approved=False, learner=u)
    complete(c, subs)
    assert not Certificate.objects.exists()


def test_pass_threshold_and_graded_attempts(learner, author, settings):
    c, u = learner
    cur, subs = course(author, learner=u)
    complete(c, subs, score=0.4)  # completed, but below the pass score
    assert not Certificate.objects.exists()
    cur2, subs2 = course(author, title="No attempts", learner=u)
    complete(c, subs2, attempt=False)  # clicked through without answering anything
    assert not Certificate.objects.exists()
    settings.CERT_PASS_SCORE = 0.3
    UserSubsectionState.objects.filter(
        user=u, subsection=subs[0]
    ).first().save()  # re-check with the lower bar
    assert Certificate.objects.filter(curriculum=cur).count() == 1


def test_assigned_course_is_issued_by_the_org(school):
    org, (mgr, mu), (kid, ku, mk) = school
    cur, subs = course(mu, title="Fire safety", approved=False, learner=ku)
    Assignment.objects.create(org=org, curriculum=cur)
    complete(kid, subs)
    cert = Certificate.objects.get()
    assert (cert.org, cert.issuer_name, cert.issuer_type, cert.issuer_slug, cert.author_name) == (
        org,
        "Vidya Matric",
        "organisation",
        "vidya",
        "Meena",
    )
    org.delete()  # the org going away must not turn it into an "Issued by Aasan" certificate
    pub = APIClient().get(f"/api/credentials/verify/{cert.code}/").data
    assert (pub["issuer"], pub["issued_by_type"]) == ("Vidya Matric", "organisation")


@pytest.mark.parametrize("name", ["Aasan", "AASAN Academy", "The aasan team", "ஆசான் பள்ளி"])
def test_reserved_issuer_names_are_refused(school, name):
    org, (mgr, mu), (kid, ku, mk) = school
    org.display_name = name
    org.save()
    cur, subs = course(mu, title="Fire safety", approved=False, learner=ku)
    Assignment.objects.create(org=org, curriculum=cur)
    complete(kid, subs)
    assert not Certificate.objects.exists()  # auto-issue skipped
    r = mgr.post(
        "/api/credentials/orgs/vidya/", {"member_id": mk.id, "kind": "course", "id": cur.id}, format="json"
    )
    assert r.status_code == 400 and r.data["code"] == "issuer_name_reserved"


def test_pdf_shows_org_and_author_lines(school):
    from apps.credentials.pdf import issuer_line

    org, (mgr, mu), (kid, ku, mk) = school
    cur, subs = course(mu, title="Fire safety", approved=False, learner=ku)
    Assignment.objects.create(org=org, curriculum=cur)
    complete(kid, subs)
    cert = Certificate.objects.get()
    assert issuer_line(cert) == "Issued by (an organisation on Aasan)"
    assert kid.get(f"/api/credentials/{cert.id}/pdf/").content[:5] == b"%PDF-"
