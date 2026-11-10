"""The sample school seeder: builds a believable school, resets instead of duplicating, and removes cleanly."""

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.credentials.models import Certificate, CertificateTemplate
from apps.orgs.models import Group, Membership, Organization, Survey

pytestmark = pytest.mark.django_db


def _run(*args):
    from io import StringIO

    out = StringIO()
    call_command("seed_sample_org", *args, stdout=out)
    return out.getvalue()


def test_builds_a_school_with_people_progress_survey_and_branding():
    owner = User.objects.create_user("owner@example.com", "Owner#Pass2026")
    out = _run("--owner", "owner@example.com")
    org = Organization.objects.get(slug="sunrise-sample-school")
    roles = dict(Membership.objects.filter(org=org).values_list("user__email", "role"))
    assert roles["owner@example.com"] == "owner" and roles["sample.lakshmi@aasan.test"] == "admin"
    assert sum(1 for r in roles.values() if r == "learner") == 24
    assert set(Group.objects.filter(org=org).values_list("name", flat=True)) == {
        "Everyone",
        "Class 9 A",
        "Class 10 A",
    }
    assert Certificate.objects.filter(org=org).count() >= 1  # the finishers were certified by the school
    assert Survey.objects.get(org=org).responses.count() == 18
    assert CertificateTemplate.objects.filter(org=org, layout="modern").exists()
    assert "SAMPLE_PASSWORD=" in out and owner.email not in out
    # every sample account is flagged as a test account by the launch checklist
    assert (
        not User.objects.filter(email__startswith="sample.").exclude(email__endswith="@aasan.test").exists()
    )


def test_rerun_resets_and_remove_cleans_up():
    _run()
    _run()
    assert Organization.objects.filter(slug="sunrise-sample-school").count() == 1
    assert User.objects.filter(email__startswith="sample.").count() == 27
    _run("--remove")
    assert not Organization.objects.filter(slug="sunrise-sample-school").exists()
    assert not User.objects.filter(email__startswith="sample.").exists()


def test_unknown_owner_is_refused():
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        _run("--owner", "nobody@example.com")
