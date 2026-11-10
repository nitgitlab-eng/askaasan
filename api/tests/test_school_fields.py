"""Milestone 9 — member fields v2: visibility (editable / read-only / hidden) + self-fill prompts."""

import pytest

from apps.orgs.models import Membership, Organization
from tests.test_school_units import client_for

pytestmark = pytest.mark.django_db

FIELDS = [
    {"key": "roll_no", "label": "Roll no.", "type": "text", "visibility": "readonly"},
    {
        "key": "section",
        "label": "Section",
        "type": "select",
        "options": ["A", "B"],
        "visibility": "editable",
        "self_fill": True,
    },
    {
        "key": "guardian_phone",
        "label": "Guardian phone",
        "type": "text",
        "visibility": "editable",
        "self_fill": True,
    },
    {"key": "fee_status", "label": "Fee status", "type": "text", "visibility": "hidden"},
]


@pytest.fixture
def setup():
    admin, au = client_for("admin@f.in")
    org = Organization.objects.create(name="Fields School", slug="fs")
    Membership.objects.create(org=org, user=au, role="owner")
    kid, ku = client_for("kid@f.in")
    m = Membership.objects.create(
        org=org, user=ku, role="learner", fields={"roll_no": "12", "fee_status": "overdue", "section": "A"}
    )
    r = admin.patch("/api/orgs/fs/settings/", {"member_fields": FIELDS}, format="json")
    assert r.status_code == 200, r.data
    return admin, kid, m


def test_settings_validate_visibility_and_self_fill(setup):
    admin, _, _ = setup
    bad = [{"key": "x", "label": "X", "type": "text", "visibility": "readonly", "self_fill": True}]
    assert admin.patch("/api/orgs/fs/settings/", {"member_fields": bad}, format="json").status_code == 400
    assert (
        admin.patch(
            "/api/orgs/fs/settings/",
            {"member_fields": [{"key": "x", "label": "X", "type": "text", "visibility": "secret"}]},
            format="json",
        ).status_code
        == 400
    )
    # old-style fields (no visibility) default to hidden from the member
    r = admin.patch(
        "/api/orgs/fs/settings/",
        {"member_fields": [{"key": "x", "label": "X", "type": "text"}]},
        format="json",
    )
    assert (
        r.data["member_fields"][0]["visibility"] == "hidden"
        and r.data["member_fields"][0]["self_fill"] is False
    )


def test_hidden_fields_never_reach_the_member(setup):
    _, kid, _ = setup
    d = kid.get("/api/orgs/me/fields/").data
    keys = [f["key"] for f in d["orgs"][0]["fields"]]
    assert keys == ["roll_no", "section", "guardian_phone"]
    assert "overdue" not in str(d) and "fee_status" not in str(d)
    by = {f["key"]: f for f in d["orgs"][0]["fields"]}
    assert by["roll_no"]["editable"] is False and by["roll_no"]["value"] == "12"
    assert by["guardian_phone"]["missing"] is True and by["section"]["missing"] is False
    assert d["missing"] == 1


def test_member_writes_only_editable_fields(setup):
    _, kid, m = setup
    assert (
        kid.patch("/api/orgs/me/fields/fs/", {"fields": {"roll_no": "99"}}, format="json").status_code == 403
    )
    assert (
        kid.patch("/api/orgs/me/fields/fs/", {"fields": {"fee_status": "paid"}}, format="json").status_code
        == 403
    )
    assert kid.patch("/api/orgs/me/fields/fs/", {"fields": {"nope": "x"}}, format="json").status_code == 403
    assert (
        kid.patch("/api/orgs/me/fields/fs/", {"fields": {"section": "Z"}}, format="json").data["code"]
        == "bad_option"
    )
    r = kid.patch(
        "/api/orgs/me/fields/fs/",
        {"fields": {"guardian_phone": "98400 00000", "section": "B"}},
        format="json",
    )
    assert r.status_code == 200 and "fee_status" not in str(r.data)
    m.refresh_from_db()
    assert m.fields == {
        "roll_no": "12",
        "fee_status": "overdue",
        "section": "B",
        "guardian_phone": "98400 00000",
    }
    assert kid.get("/api/orgs/me/fields/").data["missing"] == 0
    other, _ = client_for("stranger@f.in")
    assert (
        other.patch("/api/orgs/me/fields/fs/", {"fields": {"section": "A"}}, format="json").status_code == 404
    )
    assert other.get("/api/orgs/me/fields/").data == {"orgs": [], "missing": 0}
