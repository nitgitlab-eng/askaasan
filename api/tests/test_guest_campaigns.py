"""Guest campaigns: org-manager permissions, AI demo generation (keys stay server-side), explicit send only,
fixed subject + unsubscribe line, opt-outs and the per-org daily send limit."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.guests.campaigns import SEND_SUBJECT, parse_prospects
from apps.guests.models import GuestLink, GuestOptOut, Prospect
from apps.learning.models import Activity, Curriculum
from apps.orgs.models import Membership, Organization

pytestmark = pytest.mark.django_db
PW = "Guest#Camp2026"
PASTE = "company,email,industry\nSwift Logistics,ops@swift.test,logistics\n=Evil Co,evil@x.test,retail\nbad line\nNo Mail,not-an-email"


def member(org, email, role):
    u = User.objects.create_user(email, PW)
    Membership.objects.create(org=org, user=u, role=role)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def org():
    return Organization.objects.create(name="Demo Academy", slug="demo-academy")


@pytest.fixture
def manager(org):
    return member(org, "mgr@camp.test", "manager")


def create(c, slug="demo-academy", prospects=PASTE, capture=None):
    body = {"name": "Q3 outreach", "topic": "AI tools for everyday work", "prospects": prospects}
    if capture:
        with capture(execute=True):
            return c.post(f"/api/guests/orgs/{slug}/campaigns/", body, format="json")
    return c.post(f"/api/guests/orgs/{slug}/campaigns/", body, format="json")


def test_parse_prospects():
    rows, errors = parse_prospects(PASTE + "\nSwift Again,OPS@swift.test")
    assert [r["email"] for r in rows] == ["ops@swift.test", "evil@x.test"]  # header skipped, dupes dropped
    assert len(errors) == 2


def test_permissions(org, manager, auth):
    learner_c, _ = member(org, "kid@camp.test", "learner")
    assert create(learner_c).status_code == 403
    plain, _ = auth
    assert create(plain).status_code == 404  # non-members can't even see the org exists
    other = Organization.objects.create(name="Other", slug="other")
    oc, _ = member(other, "o@camp.test", "owner")
    c, _ = manager
    camp = create(c).data
    assert oc.get(f"/api/guests/campaigns/{camp['id']}/").status_code == 404
    pid = camp["prospects"][0]["id"]
    assert oc.post(f"/api/guests/prospects/{pid}/send/").status_code == 404
    assert oc.patch(f"/api/guests/prospects/{pid}/", {"body": "x"}, format="json").status_code == 404
    assert learner_c.post(f"/api/guests/prospects/{pid}/send/").status_code == 403


def test_generation_builds_demo_link_and_draft(manager, django_capture_on_commit_callbacks, mailoutbox):
    c, u = manager
    r = create(c, capture=django_capture_on_commit_callbacks)
    assert r.status_code == 201 and len(r.data["errors"]) == 2
    d = c.get(f"/api/guests/campaigns/{r.data['id']}/").data
    p = d["prospects"][0]
    assert p["status"] == "ready" and p["link"]["url"].endswith(p["link"]["slug"]) and p["subject"]
    assert mailoutbox == []  # nothing is sent without an explicit click
    cur = Curriculum.objects.get(pk=p["course_id"])
    assert cur.owner == u and cur.published_at and cur.visibility == "link"
    types = list(Activity.objects.filter(subsection__section__curriculum=cur).values_list("type", flat=True))
    assert types == ["quiz", "sequencing"]  # the AI's open_input was dropped: demos stay auto-graded
    assert "correct" not in str(d)  # no answer keys in the campaign view
    link = GuestLink.objects.get(pk=p["link"]["id"])
    assert link.org.slug == "demo-academy" and link.course == cur
    assert APIClient().get(f"/api/guests/public/{link.slug}/").data["brand"]["name"] == "Demo Academy"


def test_send_uses_fixed_subject_and_unsubscribe(
    org, manager, django_capture_on_commit_callbacks, mailoutbox
):
    c, _ = manager
    camp = create(c, capture=django_capture_on_commit_callbacks).data
    p = camp["prospects"][1]  # "=Evil Co" — sending reads the current DB state
    c.patch(
        f"/api/guests/prospects/{p['id']}/",
        {"subject": "URGENT: your bank account", "body": "Hi team,\nTry this."},
        format="json",
    )
    r = c.post(f"/api/guests/prospects/{p['id']}/send/")
    assert r.status_code == 200 and r.data["status"] == "sent"
    m = mailoutbox[0]
    assert m.subject == SEND_SUBJECT and m.to == ["evil@x.test"]
    assert "Try this." in m.body and "/g/" in m.body and "Unsubscribe" in m.body
    assert c.post(f"/api/guests/prospects/{p['id']}/send/").data["code"] == "already_sent"
    assert "Sent via Aasan on behalf of Demo Academy" in m.body
    unsub = m.body.split("Unsubscribe: ")[1].split()[0].split("/api/", 1)[1]
    page = APIClient().get("/api/" + unsub)  # GET (e.g. a mail scanner) only shows a confirm page
    assert page.status_code == 200 and b"<form" in page.content
    assert not GuestOptOut.objects.filter(email="evil@x.test").exists()
    token = unsub.split("t=", 1)[1]
    assert APIClient().post("/api/guests/unsubscribe/", {"t": token}).status_code == 200
    assert GuestOptOut.objects.filter(email="evil@x.test").exists()
    assert APIClient().get("/api/guests/unsubscribe/?t=forged").status_code == 400


def test_opted_out_addresses_are_skipped(manager, django_capture_on_commit_callbacks, mailoutbox):
    c, _ = manager
    GuestOptOut.objects.create(email="ops@swift.test")
    camp = create(c, capture=django_capture_on_commit_callbacks).data
    r = c.post(f"/api/guests/prospects/{camp['prospects'][0]['id']}/send/")
    assert r.status_code == 409 and r.data["code"] == "unsubscribed" and mailoutbox == []


def test_send_all_needs_confirmation_and_daily_limit(
    manager, settings, django_capture_on_commit_callbacks, mailoutbox
):
    settings.GUEST_CAMPAIGN_SENDS_PER_DAY = 1
    c, _ = manager
    camp = create(c, capture=django_capture_on_commit_callbacks).data
    assert c.post(f"/api/guests/campaigns/{camp['id']}/send-all/", {}, format="json").status_code == 400
    r = c.post(f"/api/guests/campaigns/{camp['id']}/send-all/", {"confirm": True}, format="json")
    assert (
        r.status_code == 200
        and len(r.data["sent"]) == 1
        and list(r.data["skipped"].values()) == ["daily_limit"]
    )
    assert len(mailoutbox) == 1
    left = Prospect.objects.get(status="ready")
    r = c.post(f"/api/guests/prospects/{left.id}/send/")
    assert r.status_code == 429 and r.data["code"] == "daily_limit"


def test_limits_on_prospect_count(manager):
    c, _ = manager
    many = "\n".join(f"Co {i},p{i}@x.test" for i in range(30))
    assert create(c, prospects=many).data["code"] == "too_many_prospects"
    assert create(c, prospects="nothing useful").data["code"] == "no_prospects"


def test_regenerate_keeps_same_link(manager, django_capture_on_commit_callbacks):
    c, _ = manager
    camp = create(c, capture=django_capture_on_commit_callbacks).data
    p = c.get(f"/api/guests/campaigns/{camp['id']}/").data["prospects"][0]
    with django_capture_on_commit_callbacks(execute=True):
        assert c.post(f"/api/guests/prospects/{p['id']}/regenerate/").status_code == 202
    after = c.get(f"/api/guests/campaigns/{camp['id']}/").data["prospects"][0]
    assert after["link"]["slug"] == p["link"]["slug"] and after["course_id"] != p["course_id"]
    assert not Curriculum.objects.filter(pk=p["course_id"]).exists()  # unlinked old draft cleaned up


# ── Security review regressions: send volume caps ─────────────────────


def _ready(c, cap, n=2):
    lines = "\n".join(f"Co {i},p{i}-{c.handler._force_user.id}@x.test" for i in range(n))
    camp = create(c, slug=c._org_slug, prospects=lines, capture=cap).data
    return list(Prospect.objects.filter(campaign_id=camp["id"]).values_list("id", flat=True))


def _verified_old_org(slug, owner_email):
    from datetime import timedelta

    from django.utils import timezone

    o = Organization.objects.create(name=slug.title(), slug=slug)
    Organization.objects.filter(pk=o.pk).update(created_at=timezone.now() - timedelta(days=30))
    c, u = member(o, owner_email, "owner")
    User.objects.filter(pk=u.pk).update(email_verified=True)
    c._org_slug = slug
    return c


def test_new_or_unverified_org_capped_at_five(
    org, manager, settings, django_capture_on_commit_callbacks, mailoutbox
):
    c, _ = manager
    c._org_slug = "demo-academy"
    ids = _ready(c, django_capture_on_commit_callbacks, n=7)
    codes = [c.post(f"/api/guests/prospects/{i}/send/").status_code for i in ids]
    assert codes.count(200) == 5 and codes[-1] == 429
    old = _verified_old_org("veteran", "vet@camp.test")
    ids = _ready(old, django_capture_on_commit_callbacks, n=7)
    assert all(old.post(f"/api/guests/prospects/{i}/send/").status_code == 200 for i in ids)


def test_per_account_cap_across_orgs(settings, django_capture_on_commit_callbacks, mailoutbox):
    settings.GUEST_CAMPAIGN_PER_ACCOUNT_DAY = 3
    a = _verified_old_org("org-a", "boss@camp.test")
    b_org = Organization.objects.create(name="B", slug="org-b")
    Organization.objects.filter(pk=b_org.pk).update(
        created_at=a.handler._force_user.date_joined.replace(year=2020)
    )
    Membership.objects.create(org=b_org, user=a.handler._force_user, role="owner")
    ids_a = _ready(a, django_capture_on_commit_callbacks, n=2)
    a._org_slug = "org-b"
    ids_b = _ready(a, django_capture_on_commit_callbacks, n=2)
    codes = [a.post(f"/api/guests/prospects/{i}/send/") for i in ids_a + ids_b]
    assert [r.status_code for r in codes] == [200, 200, 200, 429] and codes[-1].data[
        "code"
    ] == "account_limit"


def test_global_daily_cap(settings, django_capture_on_commit_callbacks, mailoutbox):
    settings.GUEST_CAMPAIGN_GLOBAL_PER_DAY = 2
    x = _verified_old_org("org-x", "x@camp.test")
    y = _verified_old_org("org-y", "y@camp.test")
    ix, iy = (
        _ready(x, django_capture_on_commit_callbacks, n=2),
        _ready(y, django_capture_on_commit_callbacks, n=1),
    )
    assert [x.post(f"/api/guests/prospects/{i}/send/").status_code for i in ix] == [200, 200]
    r = y.post(f"/api/guests/prospects/{iy[0]}/send/")
    assert r.status_code == 429 and r.data["code"] == "global_limit"


def test_unit_scoped_manager_refused(org, manager, django_capture_on_commit_callbacks):
    from apps.orgs.models import SubUnit, UnitAdmin

    c, _ = manager
    camp = create(c, capture=django_capture_on_commit_callbacks).data
    uc, uu = member(org, "unit@camp.test", "manager")
    Membership.objects.filter(user=uu).update(unit_scoped=True)
    UnitAdmin.objects.create(
        unit=SubUnit.objects.create(org=org, name="Primary"), membership=Membership.objects.get(user=uu)
    )
    assert uc.get("/api/guests/orgs/demo-academy/campaigns/").status_code == 403
    assert uc.get(f"/api/guests/campaigns/{camp['id']}/").status_code == 403
    assert (
        uc.post(f"/api/guests/campaigns/{camp['id']}/send-all/", {"confirm": True}, format="json").status_code
        == 403
    )
