"""Milestone 4: history (undo/redo/versions), templates, lesson picker, import/export, presets, research, chat authoring,
lecture videos, archive, reset progress, exports (pptx/xlsx), quarterly review."""

import io
import json

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.learning.models import Activity, ActivityAttempt, Curriculum, Subsection, UserSubsectionState
from apps.orgs.models import Membership, Organization
from apps.review.models import ReviewCard
from apps.studio.models import CourseRevision, LectureVideo

pytestmark = pytest.mark.django_db
PW = "Studio#2026pass"


def client_for(email, creator=False, staff=False):
    u = User.objects.create_user(email, PW, is_creator=creator, is_staff=staff)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def creator():
    return client_for("maker@aasan.test", creator=True)


def course(c, generate=True):
    cid = c.post("/api/lab/courses/", {"goal": "Teach AI basics", "mode": "ai"}, format="json").data["id"]
    d = c.get(f"/api/lab/courses/{cid}/").data
    if generate:
        for s in d["sections"]:
            for b in s["subsections"]:
                c.post(f"/api/lab/subsections/{b['id']}/generate/")
    return cid, c.get(f"/api/lab/courses/{cid}/").data


def test_undo_redo_and_named_versions(creator):
    c, _ = creator
    cid, d = course(c)
    sec = d["sections"][0]
    assert d["history"]["can_undo"]  # generation steps are undoable
    c.patch(f"/api/lab/sections/{sec['id']}/", {"title": "Renamed"}, format="json")
    c.post(f"/api/lab/sections/{sec['id']}/subsections/", {"title": "Extra lesson"}, format="json")
    h = c.get(f"/api/studio/courses/{cid}/history/").data
    assert h["can_undo"] and not h["can_redo"] and h["undo_label"] == "Add lesson"
    after = c.post(f"/api/studio/courses/{cid}/undo/").data
    assert not any(b["title"] == "Extra lesson" for b in after["sections"][0]["subsections"])
    assert after["sections"][0]["title"] == "Renamed" and after["history"]["can_redo"]
    after = c.post(f"/api/studio/courses/{cid}/undo/").data
    assert after["sections"][0]["title"] == sec["title"]
    # Lesson ids survive undo (learner progress isn't orphaned)
    assert [b["id"] for b in after["sections"][0]["subsections"]] == [b["id"] for b in sec["subsections"]]
    redo = c.post(f"/api/studio/courses/{cid}/redo/").data
    assert redo["sections"][0]["title"] == "Renamed"
    # A new edit after undo drops the redo branch
    c.patch(f"/api/lab/sections/{sec['id']}/", {"summary": "new"}, format="json")
    assert not c.get(f"/api/studio/courses/{cid}/history/").data["can_redo"]
    # Named version + restore
    c.post(f"/api/studio/courses/{cid}/versions/", {"label": "Before big change"}, format="json")
    c.delete(f"/api/lab/sections/{sec['id']}/")
    v = c.get(f"/api/studio/courses/{cid}/history/").data["versions"][0]
    restored = c.post(f"/api/studio/courses/{cid}/versions/{v['id']}/").data
    assert restored["sections"][0]["title"] == "Renamed" and restored["history"]["undo_label"].startswith(
        "Restored"
    )
    other, _ = client_for("x@aasan.test", creator=True)
    assert other.post(f"/api/studio/courses/{cid}/undo/").status_code == 404


def test_export_import_roundtrip_rebuilds_keys(creator):
    c, _ = creator
    cid, d = course(c)
    raw = c.get(f"/api/studio/courses/{cid}/export/?as=json").content.decode()
    data = json.loads(raw)
    assert data["format"] == "aasan-course"
    assert "key" not in json.dumps(
        data["sections"][0]["lessons"][0]["activities"][0]
    )  # no answer keys leave the server
    # Tamper: smuggle a fake key into an activity — import must ignore it and rebuild from source.
    act = data["sections"][0]["lessons"][0]["activities"][0]
    act["key"] = {"correct": [99]}
    r = c.post(
        "/api/studio/import/", {"format": "json", "text": json.dumps(data), "title": "Copy"}, format="json"
    )
    assert r.status_code == 201 and r.data["title"] == "Copy" and r.data["dropped_activities"] == 0
    new_acts = Activity.objects.filter(subsection__section__curriculum_id=r.data["id"])
    assert new_acts.exists() and all(a.key.get("correct") != [99] for a in new_acts)

    y = c.get(f"/api/studio/courses/{cid}/export/?as=yaml").content.decode()
    assert c.post("/api/studio/import/", {"format": "yaml", "text": y}, format="json").status_code == 201
    outline = "# Week 1: Basics\nWhat AI is.\n- What is AI: define it\n- Data: why examples matter\n# Week 2\n1. Prompts\n"
    o = c.post(
        "/api/studio/import/", {"format": "outline", "text": outline, "title": "Pasted"}, format="json"
    ).data
    assert [s["title"] for s in o["sections"]] == ["Week 1: Basics", "Week 2"]
    assert (
        o["sections"][0]["subsections"][0]["objective"] == "define it"
        and o["sections"][0]["summary"] == "What AI is."
    )
    bad = c.post("/api/studio/import/", {"format": "json", "text": '{"format": "nope"}'}, format="json")
    assert bad.status_code == 400 and bad.data["code"] == "invalid_import"
    assert (
        c.post(
            "/api/studio/import/", {"format": "yaml", "text": "!!python/object:os.system ls"}, format="json"
        ).status_code
        == 400
    )


def test_templates_and_lesson_picker(creator):
    c, u = creator
    cid, d = course(c)
    learner, lu = client_for("learner@aasan.test")
    assert not learner.get("/api/studio/templates/").data
    assert (
        c.post(f"/api/studio/courses/{cid}/template/", {"scope": "global"}, format="json").status_code == 403
    )  # staff only
    org = Organization.objects.create(name="School", slug="school", kind="school")
    Membership.objects.create(org=org, user=u, role="manager")
    Membership.objects.create(org=org, user=lu, role="learner")
    assert (
        c.post(
            f"/api/studio/courses/{cid}/template/", {"scope": "org", "org": "school"}, format="json"
        ).status_code
        == 200
    )
    rows = learner.get("/api/studio/templates/").data
    assert rows[0]["id"] == cid and rows[0]["org"] == "School"
    made = learner.post(f"/api/studio/templates/{cid}/use/").data
    assert made["kind"] == "personal" and Curriculum.objects.get(id=made["id"]).owner == lu
    mine = c.post(f"/api/studio/templates/{cid}/use/").data
    assert mine["kind"] == "authored"
    # A learner of that school who is also a creator elsewhere still only gets a personal copy (no answer keys in the Lab)
    other = Organization.objects.create(name="Own", slug="own", kind="school")
    Membership.objects.create(org=other, user=lu, role="owner")
    assert learner.post(f"/api/studio/templates/{cid}/use/").data["kind"] == "personal"
    assert not [x for x in learner.get("/api/studio/lesson-library/").data if x["course"] == d["title"]]
    # Lesson picker: reuse a lesson into another course's section
    cid2, d2 = course(c, generate=False)
    lib = c.get("/api/studio/lesson-library/?q=").data
    assert lib
    out = c.post(
        f"/api/studio/sections/{d2['sections'][0]['id']}/import-lesson/",
        {"subsection_id": lib[0]["id"]},
        format="json",
    ).data
    assert any(b["title"] == lib[0]["title"] for b in out["sections"][0]["subsections"])
    stranger, _ = client_for("stranger@aasan.test", creator=True)
    s_cid, s_d = course(stranger, generate=False)
    priv = Subsection.objects.filter(section__curriculum_id=cid2).first()
    assert (
        stranger.post(
            f"/api/studio/sections/{s_d['sections'][0]['id']}/import-lesson/",
            {"subsection_id": priv.id},
            format="json",
        ).status_code
        == 404
    )


def test_presets_documents_research_ground_generation(creator, monkeypatch):
    c, u = creator
    p = c.post(
        "/api/studio/presets/",
        {
            "name": "Exam prep",
            "tone": "exam",
            "activity_types": ["quiz", "fill_blank"],
            "lessons_per_section": 3,
            "instructions": "Use cricket examples.",
        },
        format="json",
    )
    assert p.status_code == 201
    assert (
        c.post("/api/studio/presets/", {"name": "x", "activity_types": ["evil"]}, format="json").status_code
        == 400
    )
    cid, d = course(c, generate=False)
    assert (
        c.post(f"/api/studio/courses/{cid}/preset/", {"preset_id": p.data["id"]}, format="json").data[
            "authoring"
        ]["preset"]["tone"]
        == "exam"
    )
    r = c.post(f"/api/studio/courses/{cid}/research/", {"topic": "UPI payments"}, format="json").data
    assert r["authoring"]["research"]["sources"][0]["url"].startswith("https://")
    captured = {}
    import apps.learning.services as svc

    real = svc.complete_json_sync

    def spy(task, system, user, model, **kw):
        captured.setdefault("user", user)
        return real(task, system, user, model, **kw)

    monkeypatch.setattr(svc, "complete_json_sync", spy)
    sub = d["sections"][0]["subsections"][0]["id"]
    c.post(f"/api/lab/subsections/{sub}/generate/")
    assert (
        "cricket examples" in captured["user"]
        and "Research notes" in captured["user"]
        and "quiz, fill_blank" in captured["user"]
    )
    from apps.docs.models import Document

    other_doc = Document.objects.create(owner=User.objects.create_user("o@x.in", PW), title="Not mine")
    out = c.post(
        f"/api/studio/courses/{cid}/documents/", {"document_ids": [other_doc.id]}, format="json"
    ).data
    assert out["authoring"]["documents"] == []  # only my own documents can be attached


def test_chat_authoring_propose_then_apply(creator):
    c, _ = creator
    cid, d = course(c, generate=False)
    m = c.post(f"/api/studio/courses/{cid}/chat/", {"message": "Add a practice section"}, format="json").data[
        "messages"
    ]
    turn = len(m) - 1
    assert m[turn]["role"] == "assistant" and len(m[turn]["changes"]) == 3
    before = Curriculum.objects.get(id=cid).sections.count()
    r = c.post(
        f"/api/studio/courses/{cid}/chat/apply/", {"turn": turn, "accept": [0, 1, 2]}, format="json"
    ).data
    assert r["results"][2] == "unknown_lesson"  # invented id is refused
    secs = r["course"]["sections"]
    assert (
        len(secs) == before + 1
        and secs[-1]["title"] == "Practice"
        and secs[-1]["subsections"][0]["title"] == "Try it yourself"
    )
    assert r["course"]["history"]["undo_label"].startswith("Kili: 2 changes")
    again = c.post(
        f"/api/studio/courses/{cid}/chat/apply/", {"turn": turn, "accept": [0]}, format="json"
    ).data
    assert len(again["course"]["sections"]) == before + 1  # already applied → not repeated
    assert (
        c.post(
            f"/api/studio/courses/{cid}/chat/apply/", {"turn": 0, "accept": [0]}, format="json"
        ).status_code
        == 400
    )  # user turn


def test_lecture_youtube_and_upload(creator, settings, tmp_path, django_capture_on_commit_callbacks):
    settings.MEDIA_ROOT = str(tmp_path)
    c, _ = creator
    cid, d = course(c, generate=False)
    sub = d["sections"][0]["subsections"][0]["id"]
    assert (
        c.post(
            f"/api/studio/subsections/{sub}/lectures/",
            {"youtube_url": "https://youtu.be/dQw4w9WgXcQ", "transcript": "short"},
            format="json",
        ).data["code"]
        == "transcript_required"
    )
    tr = "0:00\nWelcome to the lesson about AI.\n0:50\nModels learn from many examples, like children do.\n1:40\nThat's it."
    with django_capture_on_commit_callbacks(execute=True):
        lv = c.post(
            f"/api/studio/subsections/{sub}/lectures/",
            {"youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "transcript": tr, "duration": 120},
            format="json",
        ).data
    lv = c.get(f"/api/studio/lectures/{lv['id']}/").data
    assert lv["status"] == "ready" and len(lv["segments"]) == 2
    segs = [
        {
            **s,
            "end": s["end"] - 5,
            "checkpoints": [{**cp, "at": min(cp["at"], s["end"] - 5)} for cp in s["checkpoints"]],
        }
        for s in lv["segments"]
    ]
    b = c.post(f"/api/studio/lectures/{lv['id']}/build/", {"segments": segs}, format="json")
    assert b.status_code == 201 and b.data["built"] == 2
    vids = Activity.objects.filter(subsection_id=sub, type="video")
    assert vids.count() == 2 and vids[0].payload["video_id"] == "dQw4w9WgXcQ"
    # Upload: magic-byte sniffing; fake STT transcribes; segments then built with our own media URL.
    from django.core.files.uploadedfile import SimpleUploadedFile

    bad = SimpleUploadedFile("x.mp4", b"<html>not a video</html>", content_type="video/mp4")
    assert (
        c.post(
            f"/api/studio/subsections/{sub}/lectures/", {"file": bad, "duration": 60}, format="multipart"
        ).data["code"]
        == "unsupported_file"
    )
    mp4 = SimpleUploadedFile(
        "lecture.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200, content_type="video/mp4"
    )
    from apps.providers.models import ProviderConfig

    ProviderConfig.objects.update_or_create(capability="stt", defaults={"provider": "fake", "enabled": True})
    with django_capture_on_commit_callbacks(execute=True):
        up = c.post(
            f"/api/studio/subsections/{sub}/lectures/", {"file": mp4, "duration": 120}, format="multipart"
        ).data
    up = LectureVideo.objects.get(id=up["id"])
    assert up.status == "ready" and up.transcript == "test transcript"
    out = c.post(
        f"/api/studio/lectures/{up.id}/build/", {"segments": [{**up.segments[0], "end": 50}]}, format="json"
    )
    assert out.status_code == 201
    src = Activity.objects.filter(subsection_id=sub, type="video").last().payload["src"]
    assert src.startswith(settings.MEDIA_URL + "lectures/") and src.endswith(".mp4")
    ProviderConfig.objects.filter(capability="stt").update(enabled=False)
    mp4b = SimpleUploadedFile(
        "lecture2.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200, content_type="video/mp4"
    )
    with django_capture_on_commit_callbacks(execute=True):
        fail = c.post(
            f"/api/studio/subsections/{sub}/lectures/", {"file": mp4b, "duration": 60}, format="multipart"
        ).data
    assert LectureVideo.objects.get(id=fail["id"]).error == "stt_not_configured"  # clear error, no crash
    # External src is never accepted in a video activity
    r = c.post(
        f"/api/lab/subsections/{sub}/activities/",
        {
            "type": "video",
            "source": {
                "title": "x",
                "prompt": "p",
                "video_id": "dQw4w9WgXcQ",
                "src": "https://evil.example/v.mp4",
                "start": 0,
                "end": 0,
                "checkpoints": [{"at": 5, "question": "q", "options": ["a", "b"], "correct": [0]}],
                "explanation": "",
            },
        },
        format="json",
    )
    assert r.status_code == 400


def test_archive_hides_from_learners_and_reset_progress(creator):
    c, u = creator
    cid, d = course(c)
    c.post(f"/api/lab/courses/{cid}/publish/", {"visibility": "link"}, format="json")
    cur = Curriculum.objects.get(id=cid)
    learner, lu = client_for("kid@aasan.test")
    learner.post(f"/api/share/{cur.share_token}/enroll/")
    sub = d["sections"][0]["subsections"][0]
    c.patch(f"/api/lab/subsections/{sub['id']}/", {"archived": True}, format="json")
    view = learner.get(f"/api/learn/curriculums/{cid}/").data
    assert all(b["id"] != sub["id"] for s in view["sections"] for b in s["subsections"])
    assert learner.get(f"/api/learn/subsections/{sub['id']}/").status_code == 404
    assert c.get(f"/api/learn/subsections/{sub['id']}/").status_code == 200  # author can preview
    c.patch(f"/api/lab/subsections/{sub['id']}/", {"archived": False}, format="json")
    # progress then reset
    s2 = Subsection.objects.get(id=sub["id"])
    a = s2.activities.first()
    UserSubsectionState.objects.create(
        user=lu, subsection=s2, status="completed", completed_at=timezone.now()
    )
    ActivityAttempt.objects.create(user=lu, activity=a, answer={}, score=1, correct=True)
    ReviewCard.objects.create(user=lu, activity=a)
    r = learner.post(f"/api/learn/curriculums/{cid}/reset/").data
    assert (
        r["reset"]
        and not UserSubsectionState.objects.filter(user=lu).exists()
        and not ReviewCard.objects.filter(user=lu).exists()
    )
    assert ActivityAttempt.objects.filter(activity=a).count() == 0


def test_course_feedback_rollup_in_lab(creator):
    from apps.learning.models import LessonFeedback

    c, _ = creator
    cid, d = course(c)
    subs = [b["id"] for s in d["sections"] for b in s["subsections"]][:2]
    for i, sid in enumerate(subs):
        LessonFeedback.objects.create(
            user=User.objects.create_user(f"f{i}@x.in", PW),
            subsection_id=sid,
            rating=4 + i,
            difficulty="hard" if i else "right",
        )
    fb = c.get(f"/api/lab/courses/{cid}/").data["feedback"]
    assert fb["n"] == 2 and fb["avg"] == 4.5 and fb["hard"] == 1


def test_exports_pptx_xlsx_and_permissions(creator):
    from openpyxl import load_workbook
    from pptx import Presentation

    c, u = creator
    cid, d = course(c)
    r = c.get(f"/api/studio/courses/{cid}/export.pptx")
    assert r.status_code == 200 and r["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument.presentationml"
    )
    prs = Presentation(io.BytesIO(r.content))
    notes = [s.notes_slide.notes_text_frame.text for s in prs.slides if s.has_notes_slide]
    assert len(prs.slides) > 5 and any(
        n.startswith(("Answer", "Answers", "Correct order", "Pairs", "Groups", "Model")) for n in notes
    )
    one = c.get(f"/api/studio/courses/{cid}/export.pptx?lesson={d['sections'][0]['subsections'][0]['id']}")
    assert len(Presentation(io.BytesIO(one.content)).slides) < len(prs.slides)
    stranger, _ = client_for("s@x.in")
    assert stranger.get(f"/api/studio/courses/{cid}/export.pptx").status_code == 404
    # Org: managers download analytics; learners can't. Learner text can't become a formula.
    org = Organization.objects.create(name="Class", slug="class", kind="school")
    Membership.objects.create(org=org, user=u, role="manager")
    kid = User.objects.create_user("k@x.in", PW)
    kid.profile.display_name = '=HYPERLINK("http://evil")'
    kid.profile.save()
    Membership.objects.create(org=org, user=kid, role="learner")
    x = c.get("/api/studio/exports/orgs/class/analytics.xlsx")
    assert x.status_code == 200
    wb = load_workbook(io.BytesIO(x.content))
    assert set(wb.sheetnames) >= {"KPIs", "Daily", "At risk"}
    cells = [cell for row in wb["At risk"].iter_rows() for cell in row]
    assert any(
        isinstance(cl.value, str) and cl.value.startswith("=HYPERLINK") and cl.data_type == "s"
        for cl in cells
    )
    kc = APIClient()
    kc.force_authenticate(kid)
    assert kc.get("/api/studio/exports/orgs/class/analytics.xlsx").status_code == 403
    # Decks carry answer keys: assigning someone else's course doesn't unlock it; the org's own template does
    from apps.learning.models import Curriculum
    from apps.orgs.models import Assignment

    teacher, tu = client_for("t@x.in")
    Membership.objects.create(org=org, user=tu, role="manager")
    Assignment.objects.create(org=org, curriculum_id=cid, created_by=u)
    assert teacher.get(f"/api/studio/courses/{cid}/export.pptx").status_code == 404
    Curriculum.objects.filter(pk=cid).update(template_scope="org", template_org=org)
    assert teacher.get(f"/api/studio/courses/{cid}/export.pptx").status_code == 200
    # Own progress
    p = c.get("/api/studio/exports/progress.xlsx")
    assert p.status_code == 200 and "Summary" in load_workbook(io.BytesIO(p.content)).sheetnames


def test_quarterly_review(creator):
    c, _ = creator
    assert c.get("/api/studio/review/").data["review"] is None
    assert c.get("/api/studio/review.xlsx").status_code == 404
    r = c.post("/api/studio/review/")
    assert r.status_code == 201 and r.data["review"]["next_quarter"]
    assert c.post("/api/studio/review/").status_code == 200  # cached for the quarter
    assert c.get("/api/studio/review.xlsx").status_code == 200


def test_history_is_bounded(creator):
    from apps.studio import history

    c, _ = creator
    cid, d = course(c, generate=False)
    sec = d["sections"][0]["id"]
    for i in range(history.MAX_AUTO + 5):
        c.patch(f"/api/lab/sections/{sec}/", {"summary": f"v{i}"}, format="json")
    assert CourseRevision.objects.filter(curriculum_id=cid, pinned=False).count() == history.MAX_AUTO


def test_appended_items_get_distinct_positions(creator):
    """Regression: `max(order) or -1` treated a max of 0 as empty, so the 2nd item also got order 0."""
    c, _ = creator
    cid = c.post("/api/lab/courses/", {"goal": "Blank", "mode": "blank"}, format="json").data["id"]
    c.post(f"/api/lab/courses/{cid}/sections/", {"title": "A"}, format="json")
    d = c.post(f"/api/lab/courses/{cid}/sections/", {"title": "B"}, format="json").data
    assert [s["order"] for s in d["sections"]] == [0, 1]
    sec = d["sections"][0]["id"]
    c.post(f"/api/lab/sections/{sec}/subsections/", {"title": "L1"}, format="json")
    d = c.post(f"/api/lab/sections/{sec}/subsections/", {"title": "L2"}, format="json").data
    assert [b["order"] for b in d["sections"][0]["subsections"]] == [0, 1]
    sub = d["sections"][0]["subsections"][0]["id"]
    q = {
        "title": "Q",
        "prompt": "p",
        "options": ["a", "b"],
        "correct": [0],
        "multiple": False,
        "explanation": "",
    }
    for _ in range(2):
        r = c.post(f"/api/lab/subsections/{sub}/activities/", {"type": "quiz", "source": q}, format="json")
        assert r.status_code == 201, r.data
    assert list(Activity.objects.filter(subsection_id=sub).values_list("order", flat=True)) == [0, 1]


def test_chat_can_rename_course(creator):
    from apps.studio.models import AuthoringChat

    c, _ = creator
    cid, _ = course(c, generate=False)
    AuthoringChat.objects.create(
        curriculum_id=cid,
        messages=[
            {"role": "user", "content": "rename"},
            {
                "role": "assistant",
                "content": "ok",
                "changes": [
                    {
                        "op": "edit_course",
                        "section_id": 0,
                        "lesson_id": 0,
                        "ref": -1,
                        "title": "UPI for beginners",
                        "text": "Pay safely",
                        "key_points": [],
                        "activity_type": "",
                        "instructions": "",
                        "why": "",
                    }
                ],
            },
        ],
    )
    r = c.post(f"/api/studio/courses/{cid}/chat/apply/", {"turn": 1, "accept": [0]}, format="json").data
    assert r["course"]["title"] == "UPI for beginners" and r["course"]["description"] == "Pay safely"
