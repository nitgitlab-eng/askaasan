"""Milestone 9 — company knowledge base: background build status, bad files rejected, topics cached, graph, mentor access."""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.docs.models import Document
from apps.orgs import knowledge
from apps.orgs.extras import viewable_documents
from apps.orgs.models import Membership, Organization, OrgDocument
from tests.test_school_units import client_for

pytestmark = pytest.mark.django_db
TEXT = (
    "Leave policy: every employee gets 12 casual leaves a year. New joiners finish onboarding in their first week. "
    "Always follow the safety checklist on the shop floor.\n"
) * 3


@pytest.fixture
def org():
    admin, au = client_for("admin@kb.in")
    o = Organization.objects.create(name="KB Co", slug="kbco", kind="company")
    Membership.objects.create(org=o, user=au, role="owner")
    mgr, mu = client_for("lead@kb.in")
    Membership.objects.create(org=o, user=mu, role="manager")
    kid, ku = client_for("emp@kb.in")
    Membership.objects.create(org=o, user=ku, role="learner")
    return o, admin, au, mgr, kid, ku


def upload(c, name, data):
    return c.post("/api/orgs/kbco/knowledge/", {"file": SimpleUploadedFile(name, data)}, format="multipart")


def test_status_transitions_to_ready_with_cached_topics(org, django_capture_on_commit_callbacks, monkeypatch):
    o, admin, au, mgr, kid, ku = org
    seen = []
    real = knowledge.build

    def spy(i):
        seen.append(OrgDocument.objects.get(pk=i).status)
        real(i)
        seen.append(OrgDocument.objects.get(pk=i).status)

    monkeypatch.setattr(knowledge, "build", spy)
    with django_capture_on_commit_callbacks(execute=True):
        r = upload(admin, "handbook.txt", TEXT.encode())
    assert r.status_code == 202 and r.data["status"] == "queued"
    assert seen == ["queued", "ready"]
    od = OrgDocument.objects.get(pk=r.data["id"])
    assert od.status == "ready" and od.raw is None and od.document_id and od.document.chunks.exists()
    assert (
        od.topics == ["Leave Policy", "Onboarding", "Safety Checklist"] and od.topics_done
    )  # deduped, cached
    rows = mgr.get("/api/orgs/kbco/knowledge/").data
    assert rows[0]["status"] == "ready" and rows[0]["topics"][0] == "Leave Policy"
    g = mgr.get("/api/orgs/kbco/knowledge/graph/").data
    assert {t["label"] for t in g["topics"]} == {"Leave Policy", "Onboarding", "Safety Checklist"} and len(
        g["links"]
    ) == 3
    # building again is a no-op (status already claimed) — topics are not re-extracted
    knowledge.build(od.id)
    # staff-only by default; once an admin opts it in, learners can ask the mentor about it
    assert od.learners_can_read is False and not viewable_documents(ku).filter(pk=od.document_id).exists()
    assert (
        viewable_documents(Membership.objects.get(org=o, role="manager").user)
        .filter(pk=od.document_id)
        .exists()
    )
    assert (
        admin.patch(
            f"/api/orgs/kbco/knowledge/{od.id}/", {"learners_can_read": True}, format="json"
        ).status_code
        == 200
    )
    assert (
        mgr.patch(
            f"/api/orgs/kbco/knowledge/{od.id}/", {"learners_can_read": False}, format="json"
        ).status_code
        == 403
    )
    assert viewable_documents(ku).filter(pk=od.document_id).exists()
    assert all(d["id"] != od.document_id for d in admin.get("/api/docs/").data)
    assert any(d["document_id"] == od.document_id for d in kid.get("/api/orgs/me/documents/").data)
    assert admin.delete(f"/api/orgs/kbco/knowledge/{od.id}/").status_code == 204
    assert not Document.objects.filter(pk=od.document_id).exists()


def test_bad_files_rejected_or_failed(org, django_capture_on_commit_callbacks):
    _, admin, *_ = org
    assert upload(admin, "virus.exe", b"MZ\x90\x00binary").data["code"] == "unsupported_type"
    assert (
        upload(admin, "fake.pdf", b"not really a pdf").data["code"] == "unsupported_type"
    )  # magic bytes decide
    assert upload(admin, "notes.txt", b"\xff\xfe\x00bad").data["code"] == "not_utf8"
    big = SimpleUploadedFile("big.txt", b"a" * (10 * 1024 * 1024 + 1))
    assert admin.post("/api/orgs/kbco/knowledge/", {"file": big}, format="multipart").status_code == 413
    with django_capture_on_commit_callbacks(execute=True):
        r = upload(admin, "tiny.txt", b"too short")
    od = OrgDocument.objects.get(pk=r.data["id"])
    assert od.status == "failed" and od.error == "no_text" and od.raw is None and od.document_id is None
    with django_capture_on_commit_callbacks(execute=True):
        r = upload(admin, "broken.pdf", b"%PDF-1.4 garbage that is not a pdf")
    od = OrgDocument.objects.get(pk=r.data["id"])
    assert od.status == "failed" and od.error
    assert admin.get("/api/orgs/kbco/knowledge/graph/").data["documents"] == []


def test_permissions(org):
    _, _, _, mgr, kid, _ = org
    assert upload(mgr, "a.txt", TEXT.encode()).status_code == 403  # managers read, admins upload
    assert kid.get("/api/orgs/kbco/knowledge/").status_code == 403
    assert kid.get("/api/orgs/kbco/knowledge/graph/").status_code == 403
    stranger, _ = client_for("s@x.in")
    assert stranger.get("/api/orgs/kbco/knowledge/").status_code == 404


# ── Security regressions ─────────────────────────────────────────────


def _ready_doc(admin, capture, name="handbook.txt"):
    with capture(execute=True):
        r = upload(admin, name, TEXT.encode())
    return OrgDocument.objects.get(pk=r.data["id"])


def test_staff_only_docs_and_cohort_partners(org, django_capture_on_commit_callbacks):
    from datetime import timedelta

    from django.utils import timezone

    from apps.orgs.models import Cohort, Group, Invitation

    o, admin, au, mgr, kid, ku = org
    od = _ready_doc(admin, django_capture_on_commit_callbacks)
    assert (
        admin.patch(f"/api/orgs/kbco/knowledge/{od.id}/", {"learners_can_read": False}, format="json").data[
            "learners_can_read"
        ]
        is False
    )
    assert not viewable_documents(ku).filter(pk=od.document_id).exists()  # staff-only now
    assert (
        viewable_documents(Membership.objects.get(org=o, role="manager").user)
        .filter(pk=od.document_id)
        .exists()
    )
    assert kid.get("/api/orgs/me/documents/").data == []
    od.learners_can_read = True
    od.save()
    # a partner who joined only through a cohort invitation: no org documents, not in Everyone, no org-wide assignments
    everyone = Group.objects.create(org=o, name="Everyone")
    c = Cohort.objects.create(
        org=o, name="P", starts_at=timezone.now(), ends_at=timezone.now() + timedelta(days=3)
    )
    inv = Invitation.objects.create(org=o, email="partner@x.in", cohort=c)
    pc, pu = client_for("partner@x.in")
    pu.email_verified = True  # accepting an invitation needs a verified email
    pu.save()
    assert pc.post(f"/api/orgs/invites/{inv.token}/accept/").status_code == 200
    pm = Membership.objects.get(org=o, user=pu)
    assert pm.partner and not everyone.members.filter(pk=pm.pk).exists()
    assert not viewable_documents(pu).filter(pk=od.document_id).exists()
    assert pc.get("/api/orgs/me/documents/").data == [] and pc.get("/api/orgs/kbco/documents/").data == []
    assert viewable_documents(ku).filter(pk=od.document_id).exists()  # ordinary learners still can


def test_kb_docs_survive_uploader_and_ex_admin_loses_access(org, django_capture_on_commit_callbacks):
    o, admin, au, mgr, kid, ku = org
    od = _ready_doc(admin, django_capture_on_commit_callbacks)
    co, cu = client_for("coowner@kb.in")
    Membership.objects.create(org=o, user=cu, role="owner")
    # removed from the org: ownership moves to another owner; no more access via the old ownership
    Membership.objects.get(org=o, user=au).delete()
    od.refresh_from_db()
    assert od.document.owner_id == cu.id
    assert not viewable_documents(au).filter(pk=od.document_id).exists()
    assert admin.get(f"/api/docs/{od.document_id}/").status_code == 404
    # the new owner's account is deleted: the document passes on again instead of vanishing
    Membership.objects.create(org=o, user=au, role="admin")
    cu.delete()
    od.refresh_from_db()
    assert od.document.owner_id == au.id
    # personal notes still go with the account
    from apps.docs.models import Document

    personal = Document.objects.create(owner=ku, title="mine", filename="m.txt", kind="txt")
    ku.delete()
    assert not Document.objects.filter(pk=personal.pk).exists()


def test_docx_zip_bomb_refused(org, django_capture_on_commit_callbacks):
    import io
    import zipfile

    _, admin, *_ = org
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * (60 * 1024 * 1024))
    with django_capture_on_commit_callbacks(execute=True):
        r = upload(admin, "bomb.docx", buf.getvalue())
    od = OrgDocument.objects.get(pk=r.data["id"])
    assert od.status == "failed" and od.error == "docx_too_large"
