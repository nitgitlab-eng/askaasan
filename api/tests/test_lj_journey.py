"""Milestone 9 (lj): lesson podcasts + warm-up, listening progress, fast-track, journey order, lesson reorder."""

import pytest
from django.utils import timezone

from apps.learning.models import (
    Activity,
    ActivityAttempt,
    Curriculum,
    Enrollment,
    Section,
    Subsection,
    UserSubsectionState,
)
from apps.study.journey import STALE_AFTER_S, build_podcast, listen_part_count, split_turn, warmup
from apps.study.models import CourseOrder, FastTrackRun, ListenProgress, PodcastEpisode
from tests.test_study import _lesson, client_for

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("media_features")]


def _shared(owner):
    cur, sub, acts = _lesson(owner)
    cur.kind, cur.published_at = "authored", timezone.now()
    cur.save()
    return cur, sub, acts


# ── Podcast ──


def test_podcast_cached_two_hosts_and_private(django_capture_on_commit_callbacks):
    c, u = client_for("pod@x.in")
    cur, sub, _ = _lesson(u)
    d = c.get(f"/api/study/lessons/{sub.id}/podcast/").data
    assert d["status"] == "none" and isinstance(d["warmup"], list)
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(f"/api/study/lessons/{sub.id}/podcast/", {"lang": "en"}, format="json")
    assert r.status_code == 202 and r.data["warmup"] is not None  # the warm-up is there while it generates
    d = c.get(f"/api/study/lessons/{sub.id}/podcast/?lang=en").data
    assert (
        d["status"] == "ready"
        and {t["speaker"] for t in d["turns"]} == {"A", "B"}
        and d["hosts"] == {"A": "Meera", "B": "Arjun"}
    )
    assert (
        c.post(f"/api/study/lessons/{sub.id}/podcast/", {"lang": "en"}, format="json").status_code == 200
    )  # cached
    assert PodcastEpisode.objects.count() == 1
    assert c.get(f"/api/study/lessons/{sub.id}/podcast/?lang=xx").status_code == 400
    other, _ = client_for("stranger-pod@x.in")
    assert other.get(f"/api/study/lessons/{sub.id}/podcast/").status_code == 404
    assert other.post(f"/api/study/lessons/{sub.id}/podcast/", {}, format="json").status_code == 404
    sub.explanation_md += "\n\nMore."
    sub.save()
    assert c.get(f"/api/study/lessons/{sub.id}/podcast/?lang=en").data.get("outdated") is True


def test_split_turn_at_sentence_boundaries():
    assert split_turn("  Short one.  ") == ["Short one."]
    sentence = "Rows are records and columns are fields in every table. "  # 57 chars
    text = sentence * 30  # ~1700 chars
    parts = split_turn(text)
    assert len(parts) >= 3 and all(len(p) <= 700 for p in parts)
    assert all(p.endswith(".") for p in parts)  # cut between sentences, never mid-sentence
    assert " ".join(parts) == text.strip()
    hindi = "यह एक पंक्ति है। " * 80  # danda ends sentences too
    assert all(len(p) <= 700 and p.endswith("।") for p in split_turn(hindi))
    no_stop = "word " * 400  # one huge sentence → cut at a space
    parts = split_turn(no_stop)
    assert all(len(p) <= 700 for p in parts) and " ".join(parts) == no_stop.strip()


def test_long_podcast_turn_becomes_consecutive_turns_by_same_host(monkeypatch):
    from llm import structured
    from llm.prompts.journey import PodcastScript

    c, u = client_for("pod-long@x.in")
    _, sub, _ = _lesson(u)
    long = "A table stores rows of records. " * 60  # ~1900 chars: used to fail the whole episode
    script = PodcastScript.model_validate(
        {
            "title": "Tables",
            "host_a": "Meera",
            "host_b": "Arjun",
            "turns": [
                {"speaker": "A", "text": "What is a table?"},
                {"speaker": "B", "text": long},
                {"speaker": "A", "text": "Got it."},
                {"speaker": "B", "text": "Great."},
            ],
        }
    )
    monkeypatch.setattr(structured, "complete_json_sync", lambda *a, **k: script)
    ep = PodcastEpisode.objects.create(subsection=sub, lang="en", source_hash="x")
    build_podcast(ep.id)
    ep.refresh_from_db()
    assert ep.status == "ready" and ep.error == ""
    speakers = [t["speaker"] for t in ep.turns]
    assert speakers[0] == "A" and speakers[-2:] == ["A", "B"]
    middle = ep.turns[1:-2]
    assert (
        len(middle) >= 3
        and {t["speaker"] for t in middle} == {"B"}
        and all(len(t["text"]) <= 700 for t in middle)
    )
    assert " ".join(t["text"] for t in middle) == long.strip()


def test_podcast_provider_not_configured_is_reported(monkeypatch):
    from llm import structured
    from llm.base import LLMError

    _, u = client_for("pod-noprov@x.in")
    _, sub, _ = _lesson(u)

    def boom(*a, **k):
        raise LLMError("provider_not_configured", "no key")

    monkeypatch.setattr(structured, "complete_json_sync", boom)
    ep = PodcastEpisode.objects.create(subsection=sub, lang="en", source_hash="x")
    build_podcast(ep.id)
    ep.refresh_from_db()
    assert ep.status == "failed" and ep.error == "provider_not_configured"


def test_podcast_get_has_updated_at_and_stuck_episode_can_be_rebuilt(django_capture_on_commit_callbacks):
    from datetime import timedelta

    c, u = client_for("pod-stuck@x.in")
    _, sub, _ = _lesson(u)
    ep = PodcastEpisode.objects.create(subsection=sub, lang="en", source_hash="x")
    d = c.get(f"/api/study/lessons/{sub.id}/podcast/?lang=en").data
    assert d["status"] == "generating" and d["updated_at"] and d["stuck"] is False
    assert (
        c.post(f"/api/study/lessons/{sub.id}/podcast/", {"lang": "en"}, format="json").status_code == 200
    )  # still busy
    PodcastEpisode.objects.filter(id=ep.id).update(
        updated_at=timezone.now() - timedelta(seconds=STALE_AFTER_S + 5)
    )
    d = c.get(f"/api/study/lessons/{sub.id}/podcast/?lang=en").data
    assert d["status"] == "generating" and d["stuck"] is True
    with django_capture_on_commit_callbacks(execute=True):
        r = c.post(f"/api/study/lessons/{sub.id}/podcast/", {"lang": "en"}, format="json")
    assert r.status_code == 202
    d = c.get(f"/api/study/lessons/{sub.id}/podcast/?lang=en").data
    assert d["status"] == "ready" and d["stuck"] is False and PodcastEpisode.objects.count() == 1


@pytest.mark.parametrize("lang", ["en", "ta", "tanglish", "hi", "te", "kn", "ml", "bn", "mr", "gu"])
def test_podcast_accepts_every_reading_language(lang):
    c, u = client_for(f"pod-{lang}@x.in")
    _, sub, _ = _lesson(u)
    assert c.get(f"/api/study/lessons/{sub.id}/podcast/?lang={lang}").status_code == 200


def test_warmup_uses_key_points_never_activity_keys():
    _, u = client_for("warm@x.in")
    cur, sub, acts = _lesson(u)
    sub.key_points = [
        "Rows are records in a table",
        "Columns describe one field",
        "Primary keys identify rows",
    ]
    sub.save()
    w = warmup(sub)
    assert 2 <= len(w) <= 3
    for q in w:
        assert (
            "_____" in q["prompt"]
            and 0 <= q["answer"] < len(q["options"])
            and len(set(q["options"])) == len(q["options"])
        )
        assert any(
            q["options"][q["answer"]] in k for k in sub.key_points
        )  # the answer is the hidden key-point word
    assert "A record" not in repr(w)  # nothing from the activities' answer keys
    sub.key_points, sub.objective = [], ""
    assert warmup(sub) == []


# ── Listening progress ──


def test_listened_flag_needs_80_percent_and_never_completes():
    c, u = client_for("listen@x.in")
    cur, sub, _ = _lesson(u)
    sub.explanation_md = "# One\nA\n\n# Two\nB\n\n# Three\nC\n\n# Four\nD"
    sub.save()
    total = listen_part_count(sub.explanation_md, sub.key_points)
    assert total == 5  # 4 heading blocks + key points
    d = c.post(
        f"/api/study/lessons/{sub.id}/listened/", {"kind": "listen", "parts": [0, 1, 2]}, format="json"
    ).data
    assert d["listened"] is False and d["listen"] == 0.6
    # out-of-range and bogus parts are ignored; a client can't claim a smaller total
    d = c.post(
        f"/api/study/lessons/{sub.id}/listened/",
        {"kind": "listen", "parts": [99, -1, "3", True], "total": 1},
        format="json",
    ).data
    assert d["listened"] is False
    d = c.post(f"/api/study/lessons/{sub.id}/listened/", {"kind": "listen", "parts": [3]}, format="json").data
    assert d["listened"] is True and d["listen"] == 0.8
    assert not UserSubsectionState.objects.filter(user=u, subsection=sub, status="completed").exists()
    assert c.get(f"/api/study/courses/{cur.id}/listened/").data == {"lessons": [sub.id]}
    assert (
        c.post(
            f"/api/study/lessons/{sub.id}/listened/", {"kind": "nope", "parts": []}, format="json"
        ).status_code
        == 400
    )
    other, _ = client_for("stranger-listen@x.in")
    assert (
        other.post(
            f"/api/study/lessons/{sub.id}/listened/", {"kind": "listen", "parts": [0]}, format="json"
        ).status_code
        == 404
    )
    assert other.get(f"/api/study/courses/{cur.id}/listened/").status_code == 404


def test_podcast_listening_counts_turns(django_capture_on_commit_callbacks):
    c, u = client_for("podlisten@x.in")
    cur, sub, _ = _lesson(u)
    assert (
        c.post(
            f"/api/study/lessons/{sub.id}/listened/", {"kind": "podcast", "parts": [0]}, format="json"
        ).status_code
        == 409
    )
    with django_capture_on_commit_callbacks(execute=True):
        c.post(f"/api/study/lessons/{sub.id}/podcast/", {"lang": "en"}, format="json")
    d = c.post(
        f"/api/study/lessons/{sub.id}/listened/",
        {"kind": "podcast", "parts": [0, 1, 2, 3], "lang": "en"},
        format="json",
    ).data
    assert d["podcast"] == round(4 / 6, 3) and not d["listened"]
    d = c.post(
        f"/api/study/lessons/{sub.id}/listened/",
        {"kind": "podcast", "parts": [4], "lang": "en"},
        format="json",
    ).data
    assert d["listened"] and ListenProgress.objects.get(user=u).listened_at


# ── Fast-track ──


def test_fast_track_pass_completes_lesson_with_graded_attempts():
    from apps.credentials.services import course_completed

    client_for("ft-owner@x.in")
    c, u = client_for("ft@x.in")
    from django.contrib.auth import get_user_model

    cur, sub, _ = _shared(get_user_model().objects.get(email="ft-owner@x.in"))
    nxt = Subsection.objects.create(section=sub.section, order=1, title="Next", lesson_status="ready")
    Enrollment.objects.create(user=u, curriculum=cur)
    r = c.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    assert r.status_code == 201 and len(r.data["questions"]) == 2  # the broken AI question was dropped
    blob = repr(r.data)
    assert "correct" not in blob and "explanation" not in blob  # keys never leave the server
    ids = [q["id"] for q in r.data["questions"]]
    assert set(Activity.objects.filter(id__in=ids).values_list("kind", flat=True)) == {"fasttrack"}
    # the lesson page never lists fast-track questions
    lesson = c.get(f"/api/learn/subsections/{sub.id}/").data
    assert not {a["id"] for a in lesson["activities"]} & set(ids)
    s = c.post(
        f"/api/study/fast-track/{r.data['run_id']}/submit/",
        {"answers": {str(i): {"selected": [0]} for i in ids}},
        format="json",
    )
    assert (
        s.status_code == 200
        and s.data["passed"]
        and s.data["score"] == 1.0
        and s.data["next_subsection_id"] == nxt.id
    )
    st = UserSubsectionState.objects.get(user=u, subsection=sub)
    assert st.status == "completed" and st.score == 1.0
    assert ActivityAttempt.objects.filter(user=u, activity_id__in=ids, correct=True).count() == 2
    # graded evidence: completing the rest normally makes the course pass the certificate rule
    UserSubsectionState.objects.create(user=u, subsection=nxt, status="completed", score=1.0)
    nxt.delete()
    assert course_completed(u, cur)
    # one submission per run; a completed lesson can't be fast-tracked again
    assert (
        c.post(
            f"/api/study/fast-track/{r.data['run_id']}/submit/", {"answers": {}}, format="json"
        ).status_code
        == 409
    )
    assert c.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json").status_code == 409


def test_fast_track_fail_does_not_complete():
    c, u = client_for("ftfail@x.in")
    cur, sub, _ = _lesson(u)
    r = c.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    ids = [q["id"] for q in r.data["questions"]]
    s = c.post(
        f"/api/study/fast-track/{r.data['run_id']}/submit/",
        {"answers": {str(ids[0]): {"selected": [0]}, str(ids[1]): {"selected": [1]}}},
        format="json",
    ).data
    assert s["passed"] is False and s["score"] == 0.5 and "next_subsection_id" not in s
    assert s["results"][1]["answer"] == [0]  # revealed only after answering
    assert not UserSubsectionState.objects.filter(user=u, subsection=sub, status="completed").exists()
    assert FastTrackRun.objects.get().passed is False


def test_fast_track_permissions_and_preanswer_guard():
    c, u = client_for("ftperm@x.in")
    cur, sub, _ = _lesson(u)
    other, _ = client_for("ftother@x.in")
    assert other.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json").status_code == 404
    r = c.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    ids = [q["id"] for q in r.data["questions"]]
    assert (
        other.post(
            f"/api/study/fast-track/{r.data['run_id']}/submit/", {"answers": {}}, format="json"
        ).status_code
        == 404
    )
    # fast-track questions are unreachable through every ordinary activity endpoint (even for the run owner)
    for url in (
        f"/api/learn/activities/{ids[0]}/attempt/",
        f"/api/learn/activities/{ids[0]}/roleplay/",
        f"/api/study/activities/{ids[0]}/hint/",
    ):
        assert c.post(url, {"answer": {"selected": [1]}}, format="json").status_code == 404, url
    assert c.get(f"/api/study/activities/{ids[0]}/hints/").status_code == 404
    # malformed answers are a 400, not a 500
    for bad in (
        "x",
        {str(ids[0]): {"selected": 5}},
        {str(ids[0]): {"selected": ["0"]}},
        {str(ids[0]): {"selected": [True]}},
        {str(ids[0]): 3},
    ):
        assert (
            c.post(
                f"/api/study/fast-track/{r.data['run_id']}/submit/", {"answers": bad}, format="json"
            ).status_code
            == 400
        ), bad
    assert c.post(
        f"/api/study/fast-track/{r.data['run_id']}/submit/",
        {"answers": {str(i): {"selected": [0]} for i in ids}},
        format="json",
    ).data["passed"]


def test_fast_track_keys_not_revealed_to_another_enrolled_learner():
    from django.contrib.auth import get_user_model

    client_for("ft-own2@x.in")
    a, ua = client_for("ft-a@x.in")
    b, ub = client_for("ft-b@x.in")
    cur, sub, _ = _shared(get_user_model().objects.get(email="ft-own2@x.in"))
    Enrollment.objects.create(user=ua, curriculum=cur)
    Enrollment.objects.create(user=ub, curriculum=cur)
    r = a.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    for q in r.data["questions"]:
        assert (
            b.post(
                f"/api/learn/activities/{q['id']}/attempt/", {"answer": {"selected": [0]}}, format="json"
            ).status_code
            == 404
        )
        assert b.post(f"/api/learn/activities/{q['id']}/roleplay/", {}, format="json").status_code == 404
    assert not ActivityAttempt.objects.filter(user=ub).exists()


def test_failed_fast_track_is_not_certificate_evidence():
    from django.contrib.auth import get_user_model

    from apps.credentials.services import course_completed

    client_for("ft-own3@x.in")
    a, ua = client_for("ft-c@x.in")
    cur, sub, _ = _shared(get_user_model().objects.get(email="ft-own3@x.in"))
    Enrollment.objects.create(user=ua, curriculum=cur)
    sub.activities.all().delete()  # a reading-only lesson
    r = a.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    ids = [q["id"] for q in r.data["questions"]]
    assert not a.post(
        f"/api/study/fast-track/{r.data['run_id']}/submit/",
        {"answers": {str(i): {"selected": [3]} for i in ids}},
        format="json",
    ).data["passed"]
    a.post(f"/api/learn/subsections/{sub.id}/complete/", {}, format="json")
    assert not course_completed(ua, cur)
    assert (
        a.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json").status_code == 409
    )  # already completed
    UserSubsectionState.objects.filter(user=ua, subsection=sub).delete()
    r = a.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    ids = [q["id"] for q in r.data["questions"]]
    assert a.post(
        f"/api/study/fast-track/{r.data['run_id']}/submit/",
        {"answers": {str(i): {"selected": [0]} for i in ids}},
        format="json",
    ).data["passed"]
    assert course_completed(ua, cur)


def test_fast_track_rows_are_pruned():
    from datetime import timedelta

    c, u = client_for("ft-prune@x.in")
    cur, sub, _ = _lesson(u)
    first = c.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json").data
    c.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")  # an unanswered run is replaced
    assert not Activity.objects.filter(id__in=[q["id"] for q in first["questions"]]).exists()
    assert sub.activities.filter(kind="fasttrack").count() == 2 and FastTrackRun.objects.count() == 1
    run = FastTrackRun.objects.get()
    c.post(f"/api/study/fast-track/{run.id}/submit/", {"answers": {}}, format="json")  # failed
    FastTrackRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(days=8))
    other, ou = client_for("ft-prune2@x.in")
    sub.section.curriculum.kind, sub.section.curriculum.published_at = "authored", timezone.now()
    sub.section.curriculum.save()
    Enrollment.objects.create(user=ou, curriculum=sub.section.curriculum)
    other.post(f"/api/study/lessons/{sub.id}/fast-track/", {}, format="json")
    assert (
        not FastTrackRun.objects.filter(pk=run.pk).exists()
        and sub.activities.filter(kind="fasttrack").count() == 2
    )


# ── Course order ──


def _ready(u, title):
    return Curriculum.objects.create(owner=u, goal=title, title=title, status="ready", kind="personal")


def test_course_order_persists_and_refuses_other_users_courses():
    c, u = client_for("order@x.in")
    a, b, d = _ready(u, "A"), _ready(u, "B"), _ready(u, "D")
    other, ou = client_for("order-other@x.in")
    theirs = _ready(ou, "Theirs")
    assert c.put("/api/study/course-order/", {"ids": [a.id, theirs.id]}, format="json").status_code == 404
    assert c.put("/api/study/course-order/", {"ids": "x"}, format="json").status_code == 400
    assert c.put("/api/study/course-order/", {"ids": [b.id, a.id, d.id, a.id]}, format="json").data[
        "ids"
    ] == [b.id, a.id, d.id]
    assert [x["id"] for x in c.get("/api/learn/curriculums/").data] == [b.id, a.id, d.id]
    e = _ready(u, "E")  # a new course shows up first
    assert [x["id"] for x in c.get("/api/learn/curriculums/").data][:2] == [e.id, b.id]
    assert CourseOrder.objects.get(user=u).ids == [b.id, a.id, d.id]
    assert other.get("/api/study/course-order/").data == {"ids": []}


def test_suggest_order_returns_only_my_active_courses():
    c, u = client_for("suggest@x.in")
    assert c.post("/api/study/course-order/suggest/").status_code == 409
    ids = []
    for t in ("A", "B"):
        cur = _ready(u, t)
        sec = Section.objects.create(curriculum=cur, order=0, title="S")
        Subsection.objects.create(section=sec, order=0, title="L")
        ids.append(cur.id)
    r = c.post("/api/study/course-order/suggest/")
    assert (
        r.status_code == 200
        and sorted(r.data["order"]) == sorted(ids)
        and 999999 not in r.data["order"]
        and r.data["note"]
    )
    assert [x["id"] for x in r.data["courses"]] == r.data["order"]
    assert not CourseOrder.objects.filter(user=u).exists()  # nothing saved until the learner accepts


# ── Reorder lessons in my own course ──


def test_reorder_lessons_own_course_with_undo():
    c, u = client_for("reorder@x.in")
    cur, sub, _ = _lesson(u)
    cur.kind = "personal"
    cur.save()
    sec = sub.section
    b = Subsection.objects.create(section=sec, order=1, title="Second", lesson_status="ready")
    hidden = Subsection.objects.create(section=sec, order=2, title="Hidden", archived=True)
    url = f"/api/learn/curriculums/{cur.id}/edit/reorder/"
    assert c.post(url, {"section_id": sec.id, "lesson_ids": [b.id]}, format="json").status_code == 400
    assert (
        c.post(url, {"section_id": sec.id, "lesson_ids": [b.id, hidden.id]}, format="json").status_code == 400
    )
    r = c.post(url, {"section_id": sec.id, "lesson_ids": [b.id, sub.id]}, format="json")
    assert r.status_code == 200 and r.data["can_undo"] and "Reorder" in r.data["undo_label"]
    assert list(sec.subsections.order_by("order").values_list("id", flat=True)) == [b.id, sub.id, hidden.id]
    assert c.post(f"/api/learn/curriculums/{cur.id}/edit/undo/").status_code == 200
    assert list(sec.subsections.order_by("order").values_list("id", flat=True))[:2] == [sub.id, b.id]
    # someone else's course, or a shared course I only learn: refused
    other, _ = client_for("reorder-other@x.in")
    assert (
        other.post(url, {"section_id": sec.id, "lesson_ids": [sub.id, b.id]}, format="json").status_code
        == 404
    )
    cur.kind = "authored"
    cur.save()
    assert c.post(url, {"section_id": sec.id, "lesson_ids": [sub.id, b.id]}, format="json").status_code == 404
