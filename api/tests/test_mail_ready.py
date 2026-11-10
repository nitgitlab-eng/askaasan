"""No SMTP set up (dev console backend): email actions say so instead of claiming "sent"."""

import pytest
from django.core import mail
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.legal.mail import mail_ready
from apps.legal.models import MailConfig
from apps.orgs.models import Invitation
from tests.test_guest_links import creator, make_course, new_link, start  # noqa: F401 — fixture
from tests.test_support import client_for

pytestmark = pytest.mark.django_db
CONSOLE = "django.core.mail.backends.console.EmailBackend"


@pytest.fixture
def no_smtp(settings):
    settings.EMAIL_BACKEND = "apps.legal.mail.ConfigurableEmailBackend"
    settings.EMAIL_FALLBACK_BACKEND = CONSOLE


def test_mail_ready_follows_admin_smtp_and_fallback(settings, no_smtp):
    assert not mail_ready()
    MailConfig.objects.create(pk=1, host="smtp.example.com", from_email="hello@example.com")
    assert mail_ready()
    MailConfig.objects.filter(pk=1).update(enabled=False)
    assert not mail_ready()
    settings.EMAIL_FALLBACK_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    assert mail_ready()
    settings.EMAIL_BACKEND = CONSOLE
    assert not mail_ready()


def test_org_invite_created_but_not_emailed_returns_links(no_smtp):
    c, _ = client_for("principal@school.in")
    slug = c.post("/api/orgs/", {"name": "Sunrise School", "kind": "school"}, format="json").data["slug"]
    r = c.post(f"/api/orgs/{slug}/invitations/", {"emails": ["anu@x.in"], "role": "learner"}, format="json")
    assert r.status_code == 201 and r.data["invited"] == ["anu@x.in"]
    assert r.data["emailed"] is False and r.data["code"] == "email_not_configured"
    inv = Invitation.objects.get(email="anu@x.in")
    assert r.data["links"] == [{"email": "anu@x.in", "link": r.data["links"][0]["link"]}] and r.data["links"][
        0
    ]["link"].endswith(f"/invite/{inv.token}")
    assert mail.outbox == []


def test_guest_email_link_says_email_not_configured(creator, no_smtp):  # noqa: F811
    c, u = creator
    slug = new_link(c, make_course(u), collect_email=True)["slug"]
    g, r = start(slug, name="Priya", email="priya@example.com")
    assert r.status_code == 201
    r = g.post(f"/api/guests/public/{slug}/email-link/")
    assert r.status_code == 503 and r.data["code"] == "email_not_configured"
    # starting again with a known address still looks exactly like a new one (no enumeration)
    _, again = start(slug, name="X", email="priya@example.com")
    assert again.status_code == 201 and set(again.data) == {"token", "me"}


def test_passwordless_delete_code_not_promised(no_smtp):
    u = User.objects.create_user("g.only@x.in")
    c = APIClient()
    c.force_authenticate(u)
    r = c.post("/api/legal/delete-account/", {"confirm": "DELETE"}, format="json")
    assert r.status_code == 503 and r.data["code"] == "email_not_configured"
    assert User.objects.filter(id=u.id).exists()


def test_support_reply_saved_but_not_emailed(no_smtp):
    c, _ = client_for("rep@x.in")
    rid = c.post("/api/support/reports/", {"category": "bug", "text": "Lesson froze"}, format="json").data[
        "id"
    ]
    staff, _ = client_for("ops@aasan.in", staff=True)
    out = staff.patch(f"/api/admin/reports/{rid}/", {"reply": "Fixed, thanks!"}, format="json").data
    assert (
        out["reply"] == "Fixed, thanks!" and out["emailed"] is False and out["code"] == "email_not_configured"
    )
