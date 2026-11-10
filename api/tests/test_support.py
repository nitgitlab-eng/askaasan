"""Milestone 6: help centre (articles, search, Ask Help), problem reports + admin inbox, tours pref, daily digest."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.support.models import HelpArticle

pytestmark = pytest.mark.django_db


def client_for(email, staff=False):
    u = User.objects.create_user(email, "Support#2026pass", is_staff=staff)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


def test_articles_seeded_searchable_in_both_languages():
    anon = APIClient()
    rows = anon.get("/api/support/articles/").data
    assert len(rows) >= 12 and {"start", "learn", "teach", "account", "faq"} <= {r["category"] for r in rows}
    assert anon.get("/api/support/articles/?q=refund payment invoice").data[0]["slug"] == "plans-payments"
    assert anon.get("/api/support/articles/?q=இடைநிறுத்தம்").data[0]["slug"] == "planner-pause"  # Tamil query
    a = anon.get("/api/support/articles/create-course/").data
    assert a["body_md"].startswith("Go to") and a["body_ta_md"]
    HelpArticle.objects.filter(slug="welcome").update(published=False)
    assert anon.get("/api/support/articles/welcome/").status_code == 404


def test_ask_help_cites_only_real_articles():
    c, _ = client_for("ask@x.in")
    r = c.post("/api/support/ask/", {"question": "How do I create a new course?"}, format="json").data
    assert r["answer"] and r["found"] is True
    assert [s["slug"] for s in r["sources"]] == [
        "create-course"
    ]  # the fake model also "cited" a made-up slug — dropped
    assert c.post("/api/support/ask/", {"question": "zzqx qqzz"}, format="json").data == {
        "answer": "",
        "sources": [],
        "found": False,
    }
    assert c.post("/api/support/ask/", {"question": "x"}, format="json").status_code == 400
    assert (
        APIClient()
        .post("/api/support/ask/", {"question": "How do I create a course?"}, format="json")
        .status_code
        == 401
    )


def test_problem_reports_and_admin_inbox(mailoutbox, settings):
    c, u = client_for("rep@x.in")
    bad = c.post(
        "/api/support/reports/",
        {"category": "bug", "text": "Lesson froze", "screenshot": "https://evil.example/x.png"},
        format="json",
    )
    assert bad.status_code == 400
    r = c.post(
        "/api/support/reports/",
        {
            "category": "answer",
            "text": "The answer about UPI was wrong",
            "page": "/mentor/3",
            "ref": "answer:message:12",
            "screenshot": f"{settings.MEDIA_URL}uploads/1/shot.png",
            "browser": "Chrome",
        },
        format="json",
    )
    assert r.status_code == 201 and r.data["status"] == "new"
    assert c.post("/api/support/reports/", {"text": "x"}, format="json").status_code == 400
    assert c.get("/api/support/reports/").data[0]["id"] == r.data["id"]
    other, _ = client_for("other@x.in")
    assert other.get("/api/support/reports/").data == []
    assert c.get("/api/admin/reports/").status_code == 403
    staff, _ = client_for("ops@aasan.in", staff=True)
    inbox = staff.get("/api/admin/reports/?status=new").data
    assert (
        inbox["counts"]["new"] == 1
        and inbox["rows"][0]["ref"] == "answer:message:12"
        and inbox["rows"][0]["email"] == "rep@x.in"
    )
    out = staff.patch(
        f"/api/admin/reports/{r.data['id']}/",
        {"status": "fixed", "reply": "Thanks! We fixed that answer."},
        format="json",
    ).data
    assert out["status"] == "fixed" and out["replied_at"]
    assert (
        len(mailoutbox) == 1
        and mailoutbox[0].to == ["rep@x.in"]
        and "fixed that answer" in mailoutbox[0].body
    )
    from apps.game.models import Notification

    assert Notification.objects.filter(user=u, kind="support").exists()
    assert c.get("/api/support/reports/").data[0]["reply"].startswith("Thanks")


def test_admin_can_edit_help_articles():
    staff, _ = client_for("ed@aasan.in", staff=True)
    a = staff.post(
        "/api/admin/help/",
        {
            "slug": "exam-mode",
            "category": "faq",
            "title": "Exam mode?",
            "body_md": "Use a pause during exams.",
        },
        format="json",
    )
    assert a.status_code == 201
    staff.patch(f"/api/admin/help/{a.data['id']}/", {"title_ta": "தேர்வு முறை?"}, format="json")
    assert APIClient().get("/api/support/articles/exam-mode/").data["title_ta"] == "தேர்வு முறை?"
    learner, _ = client_for("l@x.in")
    assert (
        learner.post(
            "/api/admin/help/", {"slug": "x", "title": "x", "body_md": "x"}, format="json"
        ).status_code
        == 403
    )


def test_tours_done_preference():
    c, _ = client_for("tour@x.in")
    r = c.patch("/api/users/preferences/", {"learning": {"tours_done": ["app", "lab"]}}, format="json")
    assert r.status_code == 200 and r.data["learning"]["tours_done"] == ["app", "lab"]


def test_daily_digest_has_one_tap_links(mailoutbox, settings):
    from apps.accounts.digest import build
    from apps.accounts.preferences import upgrade
    from apps.accounts.study_reminders import send_due
    from apps.game.services import stats_for
    from apps.learning.models import Activity, Curriculum, Section, Subsection, UserSubsectionState
    from apps.review.models import ReviewCard

    c, u = client_for("digest@x.in")
    cur = Curriculum.objects.create(owner=u, goal="g", title="Excel", status="ready")
    sub = Subsection.objects.create(
        section=Section.objects.create(curriculum=cur, order=0, title="S"),
        order=0,
        title="Formulas",
        lesson_status="ready",
    )
    UserSubsectionState.objects.create(
        user=u, subsection=sub, status="in_progress", started_at=timezone.now()
    )
    ReviewCard.objects.create(
        user=u,
        activity=Activity.objects.create(subsection=sub, order=0, type="quiz", title="q", payload={}, key={}),
        due=timezone.now() - timedelta(hours=1),
    )
    s = stats_for(u)
    s.streak, s.last_active = 4, timezone.localdate() - timedelta(days=1)
    s.save()
    subject, text, html = build(u, upgrade(u.preferences.data))
    assert "4-day streak" in text and "1 review cards are due" in text and "Continue “Formulas”" in text
    assert (
        f"{settings.FRONTEND_URL}/review" in text
        and f"/learn/{cur.id}/lesson/{sub.id}" in html
        and "<a href" in html
    )
    now = timezone.localtime().replace(second=0, microsecond=0)
    p = u.preferences
    p.data = {**p.data, "learning": {"reminder_times": [now.strftime("%H:%M")], "study_days": list(range(7))}}
    p.save()
    assert send_due(now) == 1
    m = mailoutbox[-1]
    assert m.alternatives and "unsubscribe" in m.alternatives[0][0].lower() and "/review" in m.body
