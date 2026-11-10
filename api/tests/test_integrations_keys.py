"""C2 organisation API keys: hashed with a visible prefix, raw key shown once, admin-only management, scopes, per-key
throttle, revoked/suspended refused, JWTs refused on /api/v1/ and keys refused on JWT routes, every v1 route pages and
exports CSV."""

import csv
import io

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.integrations.models import OrgApiKey, hash_key
from apps.orgs.models import Assignment, Invitation, Membership, TrainingRecord
from tests.test_cred_certificates import complete, course
from tests.test_training_records import org  # noqa: F401 — shared fixture

pytestmark = pytest.mark.django_db
KEYS = "/api/orgs/acme/integrations/keys/"
V1 = "/api/v1/orgs/acme"


def make_key(org, scopes=("read:members", "read:progress", "write:members")):  # noqa: F811
    r = org["owner"].post(KEYS, {"name": "HR sync", "scopes": list(scopes)}, format="json")
    assert r.status_code == 201, r.data
    return r.data


def key_client(raw):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    return c


def test_key_is_hashed_shown_once_and_admin_only(org):  # noqa: F811
    k = make_key(org)
    raw = k["key"]
    assert raw.startswith("ak_") and len(raw) == 43 and k["prefix"] == raw[:11]
    row = OrgApiKey.objects.get()
    assert row.key_hash == hash_key(raw) and raw not in str(row.__dict__)
    listed = org["owner"].get(KEYS).data
    assert listed["keys"][0]["prefix"] == raw[:11] and "key" not in listed["keys"][0]
    assert raw not in str(listed)
    assert org["teacher"].get(KEYS).status_code == 403  # managers can't manage keys
    assert (
        org["kavya"][0].post(KEYS, {"name": "x", "scopes": ["read:members"]}, format="json").status_code
        == 403
    )
    assert org["owner"].post(KEYS, {"name": "x", "scopes": ["admin:all"]}, format="json").status_code == 400


def test_max_ten_active_keys(org):  # noqa: F811
    for _ in range(10):
        make_key(org, ["read:members"])
    r = org["owner"].post(KEYS, {"name": "x", "scopes": ["read:members"]}, format="json")
    assert r.status_code == 409 and r.data["code"] == "too_many_keys"


def test_members_read_scope_and_org_binding(org):  # noqa: F811
    raw = make_key(org, ["read:members"])["key"]
    c = key_client(raw)
    r = c.get(f"{V1}/members/")
    assert r.status_code == 200 and r.data["count"] == 4
    assert {"John", "Meena", "Bala"} <= {m["first_name"] for m in r.data["results"]}
    assert c.get(f"{V1}/assignments/").status_code == 403  # no read:progress
    assert c.post(f"{V1}/members/", {"emails": ["a@b.in"]}, format="json").status_code == 403  # no write
    from apps.orgs.models import Organization

    Organization.objects.create(name="Other", slug="other")
    assert c.get("/api/v1/orgs/other/members/").status_code == 404  # a key is bound to its own organisation
    assert OrgApiKey.objects.get().last_used_at is not None
    body = c.get(f"{V1}/members/", {"export": "csv"}).content.decode()
    assert "first_name" in body.splitlines()[0]


def test_write_members_invites_and_removes_learners_only(org):  # noqa: F811
    c = key_client(make_key(org)["key"])
    r = c.post(f"{V1}/members/", {"emails": ["new@acme.in", "NEW@acme.in"]}, format="json")
    assert r.status_code == 201 and r.data["invited"] == ["new@acme.in"]
    inv = Invitation.objects.get(email="new@acme.in")
    assert inv.role == "learner" and inv.invited_by.email == "owner@acme.in"
    r = c.post(f"{V1}/members/", {"emails": ["boss@acme.in"], "role": "admin"}, format="json")
    assert r.status_code == 201 and Invitation.objects.get(email="boss@acme.in").role == "learner"
    john = Membership.objects.get(user=org["john"][1])
    assert c.delete(f"{V1}/members/{john.id}/").status_code == 204
    assert not Membership.objects.filter(pk=john.id).exists()
    teacher = Membership.objects.get(role="manager")
    assert c.delete(f"{V1}/members/{teacher.id}/").status_code == 403


def test_progress_certificates_and_records(org):  # noqa: F811
    c = key_client(make_key(org, ["read:progress"])["key"])
    owner = org["org"].memberships.get(role="owner").user
    kc, k = org["kavya"]
    cur, subs = course(owner, title="Fire safety", approved=False, learner=k)
    a = Assignment.objects.create(org=org["org"], curriculum=cur)
    complete(kc, subs)
    r = c.get(f"{V1}/assignments/")
    assert r.status_code == 200 and r.data["results"][0]["id"] == a.id and "rows" not in r.data["results"][0]
    p = c.get(f"{V1}/assignments/{a.id}/progress/")
    assert p.status_code == 200
    mine = next(x for x in p.data["results"] if x["user_id"] == k.id)
    assert mine["pct"] == 1 and "name" not in mine and mine["first_name"]
    certs = c.get(f"{V1}/certificates/")
    assert certs.data["count"] == 1 and certs.data["results"][0]["verify_url"].endswith(
        certs.data["results"][0]["code"]
    )
    rec = c.get(f"{V1}/training-records/")
    assert rec.data["count"] == 1 and rec.data["results"][0]["title"] == "Fire safety"
    rows = list(
        csv.DictReader(io.StringIO(c.get(f"{V1}/training-records/", {"export": "csv"}).content.decode()))
    )
    assert rows[0]["learner"] == "'=HYPERLINK(evil)"  # formula-safe
    assert TrainingRecord.objects.count() == 1


def test_revoked_suspended_and_cross_auth_refused(org):  # noqa: F811
    k = make_key(org)
    c = key_client(k["key"])
    assert c.get(f"{V1}/members/").status_code == 200
    assert c.get("/api/users/me/").status_code == 401  # a key is not a user session
    assert c.get("/api/orgs/acme/members/").status_code == 401
    jwt = org["owner"]  # force-authenticated owner: no API key → refused on v1
    assert jwt.get(f"{V1}/members/").status_code in (401, 403)
    reg = APIClient().post(
        "/api/users/register/", {"email": "z@x.in", "password": "Tamil#Learn2026"}, format="json"
    )
    bearer = APIClient()
    bearer.credentials(HTTP_AUTHORIZATION=f"Bearer {reg.data['access']}")
    assert bearer.get(f"{V1}/members/").status_code == 401  # a real JWT is refused on /api/v1/
    assert key_client("ak_" + "x" * 40).get(f"{V1}/members/").status_code == 401
    assert APIClient().get(f"{V1}/members/").status_code == 401
    o = org["org"]
    o.suspended_at = timezone.now()
    o.save()
    assert c.get(f"{V1}/members/").status_code == 403
    o.suspended_at = None
    o.save()
    assert org["owner"].delete(f"{KEYS}{k['id']}/").status_code == 204
    assert c.get(f"{V1}/members/").status_code == 401


def test_per_key_throttle(org, settings):  # noqa: F811
    settings.API_KEY_RATE = "2/hour"
    a, b = key_client(make_key(org)["key"]), key_client(make_key(org)["key"])
    assert [a.get(f"{V1}/members/").status_code for _ in range(3)] == [200, 200, 429]
    assert b.get(f"{V1}/members/").status_code == 200  # each key has its own budget
