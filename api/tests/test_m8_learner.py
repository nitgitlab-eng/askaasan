"""Milestone 8 (learner side): course options, explainer videos, pulse checks, about-me, pre/post checkpoints,
confidence, Today circuits/tiers, own-course editing, onboarding extras + CV/target role, passkeys, Lab access flag."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.learning.models import ActivityAttempt, Curriculum, Section, Subsection
from apps.orgs.models import Membership, Organization
from apps.paths.models import Skill, UserSkill
from apps.study.models import AboutMe, DailyRevision, ExplainerVideo, PulseCheck
from tests.test_study import _lesson, client_for

pytestmark = pytest.mark.django_db


def test_course_options_flow_into_generation(django_capture_on_commit_callbacks):
    from apps.studio.context import generation_extras

    c, u = client_for("opts@x.in")
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(
            "/api/learn/curriculums/",
            {
                "goal": "Learn Excel",
                "tone": "exam",
                "session_minutes": 5,
                "styles": ["examples", "exercises"],
            },
            format="json",
        )
    assert r.status_code == 202 and r.data["options"] == {
        "tone": "exam",
        "session_minutes": 5,
        "styles": ["examples", "exercises"],
    }
    rules, _ = generation_extras(Curriculum.objects.get(id=r.data["id"]), "x")
    assert "exam-focused" in rules and "5-minute" in rules and "worked" in rules and "quiz" in rules
    assert (
        c.post("/api/learn/curriculums/", {"goal": "x y z", "session_minutes": 7}, format="json").status_code
        == 400
    )


@pytest.mark.usefixtures("media_features")
def test_explainer_video_is_cached_and_shared(django_capture_on_commit_callbacks):
    c, u = client_for("ev@x.in")
    cur, sub, _ = _lesson(u)
    assert c.get(f"/api/study/lessons/{sub.id}/explainer/").data["status"] == "none"
    with django_capture_on_commit_callbacks(execute=True):
        assert (
            c.post(f"/api/study/lessons/{sub.id}/explainer/", {"lang": "ta"}, format="json").status_code
            == 202
        )
    d = c.get(f"/api/study/lessons/{sub.id}/explainer/?lang=ta").data
    assert (
        d["status"] == "ready"
        and len(d["scenes"]) == 2
        and d["scenes"][0]["visual"]
        and "mangoes" in d["transcript"]
    )
    assert (
        c.post(f"/api/study/lessons/{sub.id}/explainer/", {"lang": "ta"}, format="json").status_code == 200
    )  # cached, no new charge
    assert ExplainerVideo.objects.count() == 1
    other, _ = client_for("stranger@x.in")
    assert other.get(f"/api/study/lessons/{sub.id}/explainer/").status_code == 404  # private course


def test_pulse_check_adapts_now_and_later():
    from apps.studio.context import generation_extras

    c, u = client_for("pulse@x.in")
    cur, sub, _ = _lesson(u)
    r = c.post(
        f"/api/study/lessons/{sub.id}/pulse/",
        {"pace": "fast", "difficulty": "hard", "energy": "low", "wish": "real examples"},
        format="json",
    )
    assert r.status_code == 201 and r.data["simpler"] and not r.data["extra"]
    assert PulseCheck.objects.get(user=u).difficulty == "hard"
    assert c.post(f"/api/study/lessons/{sub.id}/pulse/", {"pace": "warp"}, format="json").status_code == 400
    cur.kind = "personal"
    cur.save()
    rules, _ = generation_extras(cur, "x")
    assert "simpler" in rules and "real examples" in rules


def test_about_me_one_question_at_a_time():
    c, u = client_for("about@x.in")
    assert c.get("/api/study/about/").data["next"]["key"] == "role"
    assert (
        c.post("/api/study/about/", {"key": "role", "value": "astronaut"}, format="json").status_code == 400
    )
    d = c.post("/api/study/about/", {"key": "role", "value": "student"}, format="json").data
    assert d["next"]["key"] == "goals"
    assert c.post("/api/study/about/", {"skip": "goals"}, format="json").data["next"]["key"] == "style"
    c.post("/api/study/about/", {"key": "tools", "value": "Excel, WhatsApp"}, format="json")
    assert AboutMe.objects.get(user=u).data == {"role": "student", "tools": "Excel, WhatsApp"}


def test_pre_post_checkpoint_measures_gain(django_capture_on_commit_callbacks):
    c, u = client_for("cp@x.in")
    cur, sub, _ = _lesson(u)
    with django_capture_on_commit_callbacks(execute=True):
        c.post(f"/api/study/courses/{cur.id}/checkpoint/")
    d = c.get(f"/api/study/courses/{cur.id}/checkpoint/").data
    assert d["status"] == "ready" and len(d["questions"]) == 5 and "correct" not in d["questions"][0]
    wrong = {q["id"]: 1 for q in d["questions"]}
    pre = c.post(
        f"/api/study/courses/{cur.id}/checkpoint/submit/", {"kind": "pre", "answers": wrong}, format="json"
    ).data
    assert pre["pre"]["correct"] == 0 and "correct" not in pre["review"][0]  # the pre-test hides the key
    assert (
        c.post(
            f"/api/study/courses/{cur.id}/checkpoint/submit/",
            {"kind": "pre", "answers": wrong},
            format="json",
        ).status_code
        == 409
    )
    right = {q["id"]: 0 for q in d["questions"]}
    post = c.post(
        f"/api/study/courses/{cur.id}/checkpoint/submit/",
        {"kind": "post", "answers": right, "confidence": {"q0": 3}},
        format="json",
    ).data
    assert (
        post["gain"] == 1.0 and post["review"][0]["confidence"] == 3 and post["review"][0]["correct"] == [0]
    )
    rows = c.get("/api/study/checkpoints/").data
    assert rows[0]["course"]["id"] == cur.id and rows[0]["gain"] == 1.0


def test_confidence_is_stored_and_a_lucky_guess_comes_back_sooner():
    from apps.review.models import ReviewCard, ReviewLog

    c, u = client_for("conf@x.in")
    cur, sub, (quiz, *_) = _lesson(u)
    c.post(
        f"/api/learn/activities/{quiz.id}/attempt/",
        {"answer": {"selected": [0]}, "confidence": 1},
        format="json",
    )
    assert ActivityAttempt.objects.get(user=u).confidence == 1
    card = ReviewCard.objects.filter(user=u).first() or ReviewCard.objects.create(user=u, activity=quiz)
    c.post(
        f"/api/review/cards/{card.id}/answer/", {"answer": {"selected": [0]}, "confidence": 1}, format="json"
    )
    log = ReviewLog.objects.filter(card=card).last()
    assert log.confidence == 1 and log.rating == 2


def test_today_one_more_circuit_and_tiers():
    c, u = client_for("circuit@x.in")
    d = c.get("/api/study/today/").data
    assert d["tier"]["key"] == "seedling" and d["circuits"] == 1
    for s in d["stations"]:
        c.post("/api/study/today/done/", {"key": s["key"]}, format="json")
    d = c.get("/api/study/today/").data
    if d["total"]:
        assert d["can_add_circuit"]
        d2 = c.post("/api/study/today/circuit/").data
        assert d2["circuits"] == 2 and all(s["round"] in (1, 2) for s in d2["stations"])
    else:  # a brand-new learner may have nothing to revise yet
        assert c.post("/api/study/today/circuit/").status_code == 409
    DailyRevision.objects.filter(user=u).update(done=["a"] * 12)
    assert c.get("/api/study/today/").data["tier"]["key"] == "sprout"


def test_learner_edits_own_course_with_undo():
    c, u = client_for("edit@x.in")
    cur, sub, _ = _lesson(u)
    cur.kind = "personal"
    cur.save()
    r = c.post(
        f"/api/learn/curriculums/{cur.id}/edit/add-section/", {"request": "using AI at work"}, format="json"
    )
    assert r.status_code == 201 and r.data["can_undo"]
    assert Section.objects.filter(curriculum=cur).count() == 2
    sec = Section.objects.get(curriculum=cur, order=0)
    assert (
        c.post(
            f"/api/learn/curriculums/{cur.id}/edit/hidden/",
            {"kind": "lesson", "id": sub.id, "hidden": True},
            format="json",
        ).status_code
        == 200
    )
    assert Subsection.objects.get(id=sub.id).archived
    assert c.post(f"/api/learn/curriculums/{cur.id}/edit/undo/").status_code == 200
    assert not Subsection.objects.filter(section=sec, archived=True).exists()
    assert c.post(f"/api/learn/curriculums/{cur.id}/edit/undo/").status_code == 200
    assert Section.objects.filter(curriculum=cur).count() == 1
    other, _ = client_for("nosy@x.in")
    assert (
        other.post(
            f"/api/learn/curriculums/{cur.id}/edit/add-section/", {"request": "x y z"}, format="json"
        ).status_code
        == 404
    )
    assert c.post(f"/api/learn/curriculums/{cur.id}/edit/sideways/").status_code == 404


def test_company_role_cv_and_target_role():
    Skill.objects.get_or_create(slug="sql", defaults={"name": "SQL", "category": "data", "keywords": ["sql"]})
    c, u = client_for("career@x.in")
    r = c.post("/api/paths/company/", {"name": "Zoho"}, format="json")
    assert r.status_code == 200 and "software" in r.data["summary"]
    assert (
        c.post("/api/paths/role-summary/", {"role": "Data analyst"}, format="json").data["skills"][0]
        == "Excel"
    )
    cv = SimpleUploadedFile(
        "cv.txt",
        b"Accounts assistant at a Chennai firm. Skills: Excel, Tally, communication. Phone 98400 00000.",
        content_type="text/plain",
    )
    p = c.post("/api/paths/cv/", {"file": cv}, format="multipart").data
    assert p["current_role"] == "Accounts assistant" and "98400" not in str(p)
    assert (
        c.post(
            "/api/paths/cv/", {"file": SimpleUploadedFile("x.exe", b"MZ\x90" * 30)}, format="multipart"
        ).status_code
        == 400
    )
    t = c.post("/api/paths/target-role/", {"role": "Data analyst"}, format="json").data
    assert "SQL" in t["missing"] and t["courses"]
    assert UserSkill.objects.filter(user=u, skill__slug="sql", followed=True).exists()
    about = AboutMe.objects.get(user=u).data
    assert about["company"] == "Zoho" and about["target_role"] == "Data analyst" and "cv_summary" in about


def test_passkeys_list_rename_remove_and_lab_flag():
    from apps.accounts.models import PasskeyCredential

    c, u = client_for("pk@x.in")
    me = c.get("/api/users/me/").data
    assert me["can_author"] is False
    org = Organization.objects.create(name="S", slug="s", kind="school")
    Membership.objects.create(org=org, user=u, role="manager")
    assert c.get("/api/users/me/").data["can_author"] is True  # teachers see the Creator Lab
    pk = PasskeyCredential.objects.create(user=u, credential_id="abc", public_key=b"k")
    assert c.get("/api/users/passkeys/").data[0]["name"] == "Passkey"
    assert (
        c.patch(f"/api/users/passkeys/{pk.id}/", {"name": "My phone"}, format="json").data["name"]
        == "My phone"
    )
    other, _ = client_for("pk2@x.in")
    assert other.delete(f"/api/users/passkeys/{pk.id}/").status_code == 404
    assert c.delete(f"/api/users/passkeys/{pk.id}/").status_code == 204
