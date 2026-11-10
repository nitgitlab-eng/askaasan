"""C1 enterprise SSO: configuration hides the secret, DNS TXT domain verification (monkeypatched resolver), start URLs
per provider (PKCE S256, state, nonce, fixed redirect), the callback with real ID-token checks (tokens signed here with a
test RSA key; only the code exchange and the JWKS key fetch are replaced), refusals for wrong nonce / state / issuer /
audience / domain / tenant, single-use state, 409 for unverified accounts, enforcement with owner break-glass (passkeys
unaffected), the admin console view and break-glass, and the daily DNS re-check."""

import time
import uuid
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import StaffRole, User
from apps.orgs import sso
from apps.orgs.models import Group, Membership, Organization, OrgDomain, OrgSsoConfig

pytestmark = pytest.mark.django_db
PW = "Sso#Passw0rd2026"
TENANT = "6f1c2a52-7d4e-4b8a-9c3d-2e1f0a9b8c7d"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def user(email, name="X", verified=True):
    u = User.objects.create_user(email, PW, email_verified=verified)
    u.profile.display_name = name
    u.profile.save()
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def dns(monkeypatch):
    records: dict[str, list[str]] = {}
    calls = []

    def txt(name):
        calls.append(name)
        return list(records.get(name, []))

    monkeypatch.setattr(sso, "txt_records", txt)
    return records, calls


@pytest.fixture
def acme(settings):
    settings.FRONTEND_URL = "https://app.aasan.test"
    oc, owner = user("owner@acme.in", "Meena")
    o = Organization.objects.create(name="Acme Corp", slug="acme")
    Membership.objects.create(org=o, user=owner, role="owner")
    ac, admin = user("admin@acme.in", "Arun")
    Membership.objects.create(org=o, user=admin, role="admin")
    Group.objects.create(org=o, name="Everyone")
    sales = Group.objects.create(org=o, name="Sales")
    return {"org": o, "owner": oc, "admin": ac, "sales": sales}


def verified_domain(org, domain="acme.in"):
    return OrgDomain.objects.create(org=org, domain=domain, verified_at=timezone.now())


def configure(acme, provider="google", **kw):
    verified_domain(acme["org"])
    body = {
        "provider": provider,
        "client_id": "client-123",
        "client_secret": "super-secret-value-9876",
        "tenant_id": TENANT if provider == "microsoft" else "",
        "hosted_domains": ["acme.in"],
        "default_role": "learner",
        "default_group_id": acme["sales"].id,
        "enabled": True,
        **kw,
    }
    r = acme["owner"].put("/api/orgs/acme/sso/", body, format="json")
    assert r.status_code == 200, r.data
    return r.data


# ── Configuration and domains ────────────────────────────────────────


def test_config_hides_the_secret_and_validates(acme):
    out = configure(acme)
    assert out["client_secret"] == "••••9876" and "super-secret" not in str(out)
    assert out["redirect_uri"] == "https://app.aasan.test/sso/callback"
    cfg = OrgSsoConfig.objects.get()
    assert "super-secret" not in cfg.client_secret_enc
    keep = acme["owner"].put("/api/orgs/acme/sso/", {"client_id": "client-456"}, format="json")
    assert (
        keep.status_code == 200 and keep.data["client_secret"] == "••••9876"
    )  # blank secret keeps the old one
    bad = acme["owner"].put(
        "/api/orgs/acme/sso/", {"provider": "microsoft", "tenant_id": "common"}, format="json"
    )
    assert bad.status_code == 400 and bad.data["code"] == "bad_tenant"
    nv = acme["owner"].put("/api/orgs/acme/sso/", {"hosted_domains": ["other.in"]}, format="json")
    assert nv.status_code == 400 and nv.data["code"] == "domain_not_verified"
    o2 = Organization.objects.create(name="New", slug="new")
    Membership.objects.create(org=o2, user=User.objects.get(email="owner@acme.in"), role="owner")
    inc = acme["owner"].put("/api/orgs/new/sso/", {"client_id": "x", "enabled": True}, format="json")
    assert inc.status_code == 400 and inc.data["code"] == "incomplete"
    assert (
        acme["admin"].put("/api/orgs/acme/sso/", {"enforced": True}, format="json").data["code"]
        == "owner_only"
    )
    learner_c, lu = user("kid@acme.in")
    Membership.objects.create(org=acme["org"], user=lu, role="learner")
    assert learner_c.get("/api/orgs/acme/sso/").status_code == 403


def test_domain_claims_and_dns_verification(acme, dns):
    records, calls = dns
    c = acme["admin"]
    for bad, code in (
        ("gmail.com", "public_mailbox"),
        ("not a domain", "bad_domain"),
        ("aasan.test", "own_domain"),
    ):
        r = c.post("/api/orgs/acme/sso/domains/", {"domain": bad}, format="json")
        assert r.status_code == 400 and r.data["code"] == code, bad
    r = c.post("/api/orgs/acme/sso/domains/", {"domain": "  @ACME.in. "}, format="json")
    assert r.status_code == 201 and r.data["domain"] == "acme.in" and not r.data["verified"]
    pk, value = r.data["id"], r.data["txt_value"]
    assert value.startswith("aasan-verify=") and r.data["txt_alt_name"] == "_aasan.acme.in"
    miss = c.post(f"/api/orgs/acme/sso/domains/{pk}/verify/")
    assert miss.status_code == 400 and miss.data["code"] == "txt_not_found"
    from django.core.cache import cache

    cache.clear()  # lookups are cached 10 minutes
    records["_aasan.acme.in"] = ["v=spf1 -all", value]
    ok = c.post(f"/api/orgs/acme/sso/domains/{pk}/verify/")
    assert ok.status_code == 200 and ok.data["verified"]
    other = Organization.objects.create(name="Squat", slug="squat")
    sc, su = user("x@squat.in")
    Membership.objects.create(org=other, user=su, role="owner")
    taken = sc.post("/api/orgs/squat/sso/domains/", {"domain": "acme.in"}, format="json")
    assert taken.status_code == 409 and taken.data["code"] == "domain_taken"


def test_txt_lookups_are_cached(acme, dns):
    records, calls = dns
    dom = OrgDomain.objects.create(org=acme["org"], domain="acme.in")
    for _ in range(3):
        acme["admin"].post(f"/api/orgs/acme/sso/domains/{dom.id}/verify/")
    assert calls.count("acme.in") == 1


# ── Start ────────────────────────────────────────────────────────────


def _start(email="kavya@acme.in"):
    r = APIClient().post("/api/users/sso/start/", {"email": email}, format="json")
    assert r.status_code == 200, r.data
    u = urlsplit(r.data["url"])
    return u, {k: v[0] for k, v in parse_qs(u.query).items()}


def test_lookup_and_start_url_google(acme):
    assert APIClient().post("/api/users/sso/lookup/", {}, format="json").status_code == 400
    assert APIClient().post("/api/users/sso/lookup/", {"email": "a@b.in"}, format="json").data == {
        "sso": False
    }
    assert APIClient().get("/api/users/auth-config/").data["sso"] is False
    configure(acme)
    assert (
        APIClient().get("/api/users/auth-config/").data["sso"] is True
    )  # shows "Sign in with your organisation"
    look = APIClient().post("/api/users/sso/lookup/", {"email": "Kavya@ACME.in"}, format="json").data
    assert look == {"sso": True, "provider": "google", "org": "Acme Corp", "enforced": False}
    u, q = _start()
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://accounts.google.com/o/oauth2/v2/auth"
    assert q["redirect_uri"] == "https://app.aasan.test/sso/callback" and q["client_id"] == "client-123"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["hd"] == "acme.in" and q["state"] and q["nonce"] and q["scope"] == "openid email profile"
    assert APIClient().post("/api/users/sso/start/", {"email": "x@else.in"}, format="json").status_code == 404


def test_start_url_microsoft_uses_the_tenant(acme):
    configure(acme, provider="microsoft")
    u, q = _start()
    assert (
        f"{u.scheme}://{u.netloc}{u.path}"
        == f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
    )
    assert q["domain_hint"] == "acme.in" and "hd" not in q


# ── Callback ─────────────────────────────────────────────────────────


@pytest.fixture
def idp(monkeypatch):
    """The provider: exchange_code returns whatever ID token the test minted; signing_key returns our public key."""
    state = {"claims": None, "key": KEY, "codes": []}

    def mint(cfg, code, verifier):
        state["codes"].append((code, verifier))
        return jwt.encode(state["claims"], state["key"], algorithm="RS256")

    monkeypatch.setattr(sso, "exchange_code", mint)
    monkeypatch.setattr(sso, "signing_key", lambda cfg, token: KEY.public_key())
    return state


def google_claims(q, **kw):
    now = int(time.time())
    return {
        "iss": "https://accounts.google.com",
        "aud": "client-123",
        "sub": "g-42",
        "email": "kavya@acme.in",
        "email_verified": True,
        "hd": "acme.in",
        "name": "Kavya R",
        "nonce": q["nonce"],
        "iat": now,
        "exp": now + 600,
        **kw,
    }


def _callback(q, code="auth-code"):
    return APIClient().post("/api/users/sso/callback/", {"code": code, "state": q["state"]}, format="json")


def test_callback_signs_in_creates_and_joins(acme, idp):
    configure(acme)
    _, q = _start()
    idp["claims"] = google_claims(q)
    r = _callback(q)
    assert r.status_code == 200, r.data
    assert r.data["created"] is True and r.data["access"] and r.data["org"] == "acme"
    u = User.objects.get(email="kavya@acme.in")
    assert u.sso_subject == "https://accounts.google.com|g-42" and u.email_verified
    m = Membership.objects.get(org=acme["org"], user=u)
    assert m.role == "learner" and acme["sales"].members.filter(pk=m.pk).exists()
    assert idp["codes"][0][0] == "auth-code" and len(idp["codes"][0][1]) >= 43  # the PKCE verifier went along
    _, q2 = _start()
    idp["claims"] = google_claims(q2)
    again = _callback(q2)
    assert again.status_code == 200 and again.data["created"] is False and again.data["user"]["id"] == u.id


def test_state_is_single_use_and_must_exist(acme, idp):
    configure(acme)
    _, q = _start()
    idp["claims"] = google_claims(q)
    assert _callback(q).status_code == 200
    replay = _callback(q)
    assert replay.status_code == 400 and replay.data["detail"] == "invalid_state"
    assert _callback({"state": "made-up"}).status_code == 400
    assert APIClient().post("/api/users/sso/callback/", {}, format="json").status_code == 400


@pytest.mark.parametrize(
    "change,code,http",
    [
        ({"nonce": "wrong"}, "invalid_sso_token", 401),
        ({"iss": "https://evil.example.com"}, "invalid_sso_token", 401),
        ({"aud": "someone-else"}, "invalid_sso_token", 401),
        ({"exp": int(time.time()) - 3600}, "invalid_sso_token", 401),
        ({"email_verified": False}, "sso_email_unverified", 401),
        ({"hd": "other.in"}, "sso_domain_not_allowed", 403),
        ({"email": "kavya@other.in"}, "sso_domain_not_allowed", 403),
        ({"email": ""}, "sso_email_missing", 401),
    ],
)
def test_bad_id_tokens_are_refused(acme, idp, change, code, http):
    configure(acme)
    _, q = _start()
    idp["claims"] = google_claims(q, **change)
    r = _callback(q)
    assert r.status_code == http and r.data["detail"] == code
    assert not User.objects.filter(email__startswith="kavya@").exists()


def test_token_signed_by_another_key_is_refused(acme, idp):
    configure(acme)
    _, q = _start()
    idp["claims"], idp["key"] = google_claims(q), OTHER_KEY
    assert _callback(q).data["detail"] == "invalid_sso_token"


def test_microsoft_tenant_must_match(acme, idp):
    configure(acme, provider="microsoft")
    _, q = _start()
    base = google_claims(q, iss=f"https://login.microsoftonline.com/{TENANT}/v2.0", tid=TENANT)
    base.pop("hd")
    base.pop("email_verified")
    idp["claims"] = {**base, "tid": str(uuid.uuid4())}
    r = _callback(q)
    assert r.status_code == 403 and r.data["detail"] == "sso_tenant_mismatch"
    _, q = _start()
    idp["claims"] = {**base, "nonce": q["nonce"]}
    assert _callback(q).status_code == 200


def test_unverified_password_account_gets_409(acme, idp):
    configure(acme)
    user("kavya@acme.in", verified=False)
    _, q = _start()
    idp["claims"] = google_claims(q)
    r = _callback(q)
    assert r.status_code == 409 and r.data["detail"] == "account_unverified"
    assert User.objects.get(email="kavya@acme.in").sso_subject is None


def test_unverified_domain_is_refused_even_if_listed(acme, idp):
    configure(acme)
    _, q = _start()
    OrgDomain.objects.filter(domain="acme.in").update(verified_at=None)
    idp["claims"] = google_claims(q)
    assert _callback(q).data["detail"] == "sso_domain_not_allowed"


# ── Enforcement ──────────────────────────────────────────────────────


def _login(email):
    return APIClient().post("/api/users/login/", {"email": email, "password": PW}, format="json")


def test_enforcement_with_owner_break_glass_and_passkeys_unaffected(acme):
    _, member = user("kavya@acme.in")
    owner = User.objects.get(email="owner@acme.in")
    assert _login("kavya@acme.in").status_code == 200  # enabled but not enforced: passwords still work
    configure(acme, enforced=True)
    r = _login("kavya@acme.in")
    assert r.status_code == 403 and r.data["detail"] == "sso_required" and r.data["org"] == "Acme Corp"
    assert _login("owner@acme.in").status_code == 200  # the owner keeps a way in if the IdP breaks
    reg = APIClient().post(
        "/api/users/register/",
        {"email": "new@acme.in", "password": PW, "accept_terms": True, "age_band": "adult"},
        format="json",
    )
    assert reg.status_code == 403 and reg.data["detail"] == "sso_required"
    assert _login("someone@else.in").status_code == 401  # other domains are untouched
    assert APIClient().post("/api/users/passkey/authenticate/begin/").status_code == 200
    assert owner.memberships.get().role == "owner" and member.is_active


def test_disabling_sso_drops_enforcement(acme):
    configure(acme, enforced=True)
    r = acme["owner"].put("/api/orgs/acme/sso/", {"enabled": False}, format="json")
    assert r.data["enabled"] is False and r.data["enforced"] is False
    user("kavya@acme.in")
    assert _login("kavya@acme.in").status_code == 200


def test_admin_console_shows_sso_and_support_can_switch_it_off(acme):
    configure(acme, enforced=True)
    staff = User.objects.create_user("ops@aasan.in", PW, is_staff=True)
    StaffRole.objects.update_or_create(user=staff, defaults={"roles": ["support"]})
    c = APIClient()
    c.force_authenticate(staff)
    d = c.get(f"/api/admin/orgs/{acme['org'].id}/").data["sso"]
    assert d["enabled"] and d["enforced"] and d["domains"] == [{"domain": "acme.in", "verified": True}]
    assert "client" not in str(d)
    assert (
        c.patch(f"/api/admin/orgs/{acme['org'].id}/", {"sso_enabled": True}, format="json").status_code == 400
    )
    r = c.patch(f"/api/admin/orgs/{acme['org'].id}/", {"sso_enabled": False}, format="json")
    assert r.status_code == 200 and r.data["sso"]["enabled"] is False and r.data["sso"]["enforced"] is False


# ── Daily DNS re-check ───────────────────────────────────────────────


def test_recheck_unverifies_after_seven_failing_days(acme, dns):
    records, _ = dns
    configure(acme, enforced=True)
    dom = OrgDomain.objects.get()
    records["acme.in"] = [f"aasan-verify={dom.token}"]
    assert sso.recheck_domains() == {"kept": 1, "dropped": 0}
    records.clear()
    assert sso.recheck_domains() == {"kept": 0, "dropped": 0}
    dom.refresh_from_db()
    assert dom.failing_since and dom.verified_at
    OrgDomain.objects.filter(pk=dom.pk).update(failing_since=timezone.now() - timedelta(days=8))
    assert sso.recheck_domains()["dropped"] == 1
    cfg = OrgSsoConfig.objects.get()
    assert not OrgDomain.objects.get().verified_at and cfg.hosted_domains == [] and not cfg.enforced
