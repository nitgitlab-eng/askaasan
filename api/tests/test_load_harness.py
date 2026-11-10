"""Load-test tooling: the seed_load_users command and the scripts/load_test.py harness (compiled + pure helpers)."""

import base64
import importlib.util
import json
import os
import py_compile
import stat
import sys
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.accounts.models import User

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "load_test.py"
SAFE = "--i-know-this-is-not-production"


def seed(tmp_path, *args, name="tokens.json") -> tuple[list[dict], str]:
    out = tmp_path / name
    buf = StringIO()
    call_command("seed_load_users", "--out", str(out), *args, stdout=buf, stderr=StringIO())
    return json.loads(out.read_text()), buf.getvalue()


@pytest.fixture
def debug_on(settings):
    settings.DEBUG = True


# ── safety rails ──


@pytest.mark.django_db
def test_refuses_without_the_not_production_flag(tmp_path, debug_on):
    with pytest.raises(CommandError, match="not-production"):
        seed(tmp_path, "--count", "2")
    assert not User.objects.filter(email__endswith="@load.aasan.test").exists()


@pytest.mark.django_db
def test_refuses_when_debug_is_off_unless_allowed(tmp_path, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError, match="DEBUG is off"):
        seed(tmp_path, "--count", "2", SAFE)
    rows, _ = seed(tmp_path, "--count", "2", SAFE, "--allow-non-debug")
    assert len(rows) == 2


@pytest.mark.django_db
def test_rejects_a_bad_prefix(tmp_path, debug_on):
    with pytest.raises(CommandError, match="prefix"):
        seed(tmp_path, "--count", "2", "--prefix", "x@y", SAFE)


# ── accounts and tokens ──


@pytest.mark.django_db
def test_creates_ready_learners_and_a_private_token_file(tmp_path, debug_on):
    rows, out = seed(tmp_path, "--count", "3", "--prefix", "lt", SAFE)
    assert [r["email"] for r in rows] == [f"lt{i:04d}@load.aasan.test" for i in range(3)]
    assert "eyJ" not in out  # tokens are never printed
    mode = stat.S_IMODE(os.stat(tmp_path / "tokens.json").st_mode)
    assert mode == 0o600
    for r in rows:
        u = User.objects.get(email=r["email"])
        assert u.email_verified and u.terms_version and u.age_band == "adult"
        assert not u.has_usable_password()
        assert u.profile.onboarding_completed
        assert u.preferences.data
        assert AccessToken(r["access"])["user_id"] in (u.id, str(u.id))
    # The token really works against the API.
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {rows[0]['access']}")
    res = c.get("/api/users/me/")
    assert res.status_code == 200 and res.data["email"] == rows[0]["email"]
    assert c.get("/api/study/today/").status_code == 200
    # The refresh token is accepted by the refresh endpoint (the harness relies on the body fallback).
    res = APIClient().post("/api/users/refresh-token/", {"refresh": rows[0]["refresh"]}, format="json")
    assert res.status_code == 200 and res.data["access"]


@pytest.mark.django_db
def test_rerunning_is_idempotent_and_resets_mentor_usage(tmp_path, debug_on):
    from apps.billing.models import UsageEvent

    first, _ = seed(tmp_path, "--count", "2", SAFE)
    u = User.objects.get(email=first[0]["email"])
    UsageEvent.objects.create(user=u, metric="mentor_message")
    u.profile.onboarding_completed = False
    u.profile.save()
    second, _ = seed(tmp_path, "--count", "3", SAFE)
    assert User.objects.filter(email__endswith="@load.aasan.test").count() == 3
    assert [r["email"] for r in second[:2]] == [r["email"] for r in first]
    assert not UsageEvent.objects.filter(user=u, metric="mentor_message").exists()
    u.profile.refresh_from_db()
    assert u.profile.onboarding_completed  # repaired


@pytest.mark.django_db
def test_handles_issue_tokens_returning_a_tuple(tmp_path, debug_on, monkeypatch):
    from apps.accounts import tokens

    monkeypatch.setattr(tokens, "issue_tokens", lambda user: ("acc-" + str(user.id), "ref-" + str(user.id)))
    rows, _ = seed(tmp_path, "--count", "1", SAFE)
    assert rows[0]["access"].startswith("acc-") and rows[0]["refresh"].startswith("ref-")


# ── extras: workshop run, course, org ──


@pytest.mark.django_db
def test_create_workshop_run_starts_a_session_per_learner(tmp_path, debug_on):
    from apps.workshops.models import WorkshopSession

    rows, out = seed(tmp_path, "--count", "2", "--create-workshop-run", SAFE)
    assert "prompt-engineering" in out
    run_ids = {r["run_id"] for r in rows}
    assert len(run_ids) == 1
    for r in rows:
        s = WorkshopSession.objects.get(pk=r["session_id"])
        assert s.user.email == r["email"] and s.started_at and s.status == "active"
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {rows[0]['access']}")
    assert c.get(f"/api/workshops/sessions/{rows[0]['session_id']}/").status_code == 200
    assert c.post(f"/api/workshops/runs/{rows[0]['run_id']}/session/").data["id"] == rows[0]["session_id"]

    # Re-seeding the same run gives fresh sessions; --keep-sessions keeps them.
    again, _ = seed(tmp_path, "--count", "2", "--workshop-run", str(rows[0]["run_id"]), SAFE)
    assert {r["session_id"] for r in again}.isdisjoint({r["session_id"] for r in rows})
    kept, _ = seed(
        tmp_path, "--count", "2", "--workshop-run", str(rows[0]["run_id"]), "--keep-sessions", SAFE
    )
    assert [r["session_id"] for r in kept] == [r["session_id"] for r in again]


@pytest.mark.django_db
def test_workshop_run_options_are_validated(tmp_path, debug_on):
    with pytest.raises(CommandError, match="either"):
        seed(tmp_path, "--count", "1", "--workshop-run", "1", "--create-workshop-run", SAFE)
    with pytest.raises(CommandError, match="No workshop run"):
        seed(tmp_path, "--count", "1", "--workshop-run", "999999", SAFE)


@pytest.mark.django_db
def test_course_and_org_enrolment(tmp_path, debug_on):
    from apps.learning.models import Curriculum, Enrollment
    from apps.orgs.models import Membership, Organization

    owner = User.objects.create_user("owner@example.com")
    draft = Curriculum.objects.create(owner=owner, kind="authored", goal="D", title="D", status="ready")
    with pytest.raises(CommandError, match="not published"):
        seed(tmp_path, "--count", "1", "--course", str(draft.id), SAFE)
    cur = Curriculum.objects.create(
        owner=owner, kind="authored", goal="G", title="G", status="ready", published_at=timezone.now()
    )
    org = Organization.objects.create(name="Load Org", slug="load-org")
    rows, _ = seed(tmp_path, "--count", "2", "--course", str(cur.id), "--org", "load-org", SAFE)
    assert all(r["course_id"] == cur.id for r in rows)
    assert Enrollment.objects.filter(curriculum=cur).count() == 2
    assert Membership.objects.filter(org=org, role="learner").count() == 2
    seed(tmp_path, "--count", "2", "--course", str(cur.id), "--org", "load-org", SAFE)  # no duplicates
    assert Enrollment.objects.filter(curriculum=cur).count() == 2
    assert Membership.objects.filter(org=org).count() == 2
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {rows[0]['access']}")
    assert c.get(f"/api/learn/curriculums/{cur.id}/").status_code == 200
    with pytest.raises(CommandError, match="No organization"):
        seed(tmp_path, "--count", "1", "--org", "nope", SAFE)


# ── the harness script ──


def _harness():
    spec = importlib.util.spec_from_file_location("aasan_load_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses look their module up while the class is built
    spec.loader.exec_module(mod)
    return mod


def test_load_test_script_compiles():
    py_compile.compile(str(SCRIPT), doraise=True)


def test_harness_helpers():
    lt = _harness()
    assert lt.pct([], 50) is None
    assert lt.pct([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) in (5, 6)
    body = base64.urlsafe_b64encode(json.dumps({"exp": 1234}).encode()).decode().rstrip("=")
    assert lt.jwt_exp(f"eyJhbGciOiJIUzI1NiJ9.{body}.sig") == 1234
    assert lt.jwt_exp("garbage") == 0.0
    assert "eyJ" not in lt.scrub("bad token eyJabc.def.ghi here")
    creds = [{"session_id": 1}] * 3 + [{}] * 7
    roles = lt.assign_roles(creds, 10, 0.2, 0.2, smoke=False)
    assert roles[:2] == ["mentor", "mentor"] and roles[2] == "workshop" and roles[3] == "reader"
    assert roles.count("reader") == 7  # no session_id → the would-be workshop VU reads instead
    smoke = lt.assign_roles([{"session_id": 1}] * 5, 5, 0.0, 0.0, smoke=True)
    assert smoke.count("mentor") == 1 and smoke.count("workshop") == 1


def test_harness_cli_defaults_and_smoke():
    lt = _harness()
    cfg = lt.parse(["--tokens", "t.json"])
    assert (cfg.base, cfg.users, cfg.ramp, cfg.duration, cfg.mix) == (
        "http://localhost:8080",
        500,
        60,
        300,
        "default",
    )
    assert cfg.origin == "http://localhost:8080" and cfg.ws_base == "ws://localhost:8080"
    s = lt.parse(["--tokens", "t.json", "--smoke", "--base", "https://aasan.example/", "--origin", "x://y"])
    assert (s.users, s.duration) == (5, 20.0)
    assert s.ws_base == "wss://aasan.example" and s.origin == "x://y"


def test_summary_never_contains_tokens_and_counts_errors():
    lt = _harness()
    st = lt.Stats()
    st.hit("GET /api/users/me/", 0.01)
    st.hit("GET /api/users/me/", 0.03)
    st.err("GET /api/users/me/", 500)
    st.hit("WS mentor connect", 0.002)
    st.err("WS mentor connect", "InvalidStatus")
    cfg = lt.parse(["--tokens", "t.json", "--users", "2"])
    res = lt.summarize(st, cfg, 10.0, {"reader": 2})
    me = res["endpoints"]["GET /api/users/me/"]
    assert me["ok"] == 2 and me["errors"] == 1 and me["error_codes"] == {"500": 1}
    assert res["http"]["requests"] == 3 and res["sockets"] == {"connects_ok": 1, "connect_failures": 1}
    assert res["errors_total"] == 2 and res["error_rate"] == pytest.approx(2 / 5, abs=1e-3)
    assert "eyJ" not in json.dumps(res)
