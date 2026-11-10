"""Connect Claude: OAuth 2.1 (metadata, DCR, PKCE code flow, refresh rotation + reuse detection, revocation),
the MCP JSON-RPC endpoint (auth, errors, tools, org scoping) and the audit log."""

import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.connect.models import AuthCode, ConnectAuditLog, Grant, OAuthClient, Token
from apps.guests.models import GuestLink
from apps.learning.models import Activity, Curriculum, Section, Subsection
from apps.orgs.models import Assignment, Membership, Organization, Survey, SurveyResponse

pytestmark = pytest.mark.django_db
PW = "Connect#Mcp2026"
REDIRECT = "https://claude.ai/api/mcp/auth_callback"
VERIFIER = "v" * 20 + "erifier-0123456789_abcdefghijklmnop~."
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "t", "version": "1"},
    },
}


def member(org, email, role, **kw):
    u = User.objects.create_user(email, PW)
    Membership.objects.create(org=org, user=u, role=role, **kw)
    c = APIClient()
    c.force_authenticate(u)
    return c, u


@pytest.fixture
def org():
    return Organization.objects.create(name="Demo Academy", slug="demo-academy")


@pytest.fixture
def admin(org):
    return member(org, "admin@mcp.test", "admin")


def register(redirect_uris=(REDIRECT,), **extra):
    return APIClient().post(
        "/api/connect/oauth/register",
        {"client_name": "Claude", "redirect_uris": list(redirect_uris), **extra},
        format="json",
    )


def auth_params(client_id, **over):
    p = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
        "scope": "org:admin",
        "state": "xyz",
        "resource": "http://localhost:5173/api/mcp",
    }
    p.update(over)
    return {k: v for k, v in p.items() if v is not None}


def approve(c, client_id, org="demo-academy", **over):
    return c.post(
        "/api/connect/authorize/",
        {**auth_params(client_id, **over), "org": org, "decision": "approve"},
        format="json",
    )


def code_from(redirect):
    q = parse_qs(urlsplit(redirect).query)
    assert q["state"] == ["xyz"] and q["iss"] == ["http://localhost:5173"]
    return q["code"][0]


def form(path, data):
    return APIClient().post(path, urlencode(data), content_type="application/x-www-form-urlencoded")


def exchange(client_id, code, verifier=VERIFIER, **extra):
    return form(
        "/api/connect/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": REDIRECT,
            "code_verifier": verifier,
            **extra,
        },
    )


def refresh(client_id, rt):
    return form(
        "/api/connect/oauth/token",
        {"grant_type": "refresh_token", "refresh_token": rt, "client_id": client_id},
    )


def connect(admin_c, org="demo-academy"):
    cid = register().data["client_id"]
    code = code_from(approve(admin_c, cid, org).data["redirect"])
    r = exchange(cid, code)
    assert r.status_code == 200, r.data
    return cid, r.data


def mcp(token, body, **headers):
    c = APIClient()
    if token:
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}", **headers)
    elif headers:
        c.credentials(**headers)
    return c.post(
        "/api/mcp", json.dumps(body) if not isinstance(body, bytes) else body, content_type="application/json"
    )


def call(token, name, args=None, id_=7):
    r = mcp(
        token,
        {
            "jsonrpc": "2.0",
            "id": id_,
            "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        },
    )
    assert r.status_code == 200, r.content
    return r.json()


# ── Metadata + DCR ────────────────────────────────────────────────────


def test_metadata_documents():
    c = APIClient()
    for path in ("/api/.well-known/oauth-authorization-server", "/.well-known/oauth-authorization-server"):
        m = c.get(path).json()
        assert m["issuer"] == "http://localhost:5173"
        assert m["code_challenge_methods_supported"] == ["S256"]
        assert m["token_endpoint"].endswith("/api/connect/oauth/token")
        assert m["registration_endpoint"].endswith("/api/connect/oauth/register")
        assert m["authorization_endpoint"] == "http://localhost:5173/connect/authorize"
        assert set(m["grant_types_supported"]) == {"authorization_code", "refresh_token"}
        assert m["token_endpoint_auth_methods_supported"] == ["none"]
    for path in (
        "/api/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/api/mcp",
    ):
        m = c.get(path).json()
        assert m["resource"] == "http://localhost:5173/api/mcp"
        assert m["authorization_servers"] == ["http://localhost:5173"]
    assert c.post("/api/.well-known/oauth-authorization-server").status_code == 405


@pytest.mark.parametrize(
    "uris,ok",
    [
        ([REDIRECT], True),
        (["http://localhost:6274/cb"], True),
        (["http://127.0.0.1:33418/callback"], True),
        (["http://evil.example/cb"], False),
        (["javascript:alert(1)"], False),
        (["https://x.test/cb#frag"], False),
        (["https://user:pw@x.test/cb"], False),
        ([], False),
        ([REDIRECT] * 6, False),
        (["ftp://x.test/cb"], False),
        ("nope", False),
    ],
)
def test_dcr_redirect_validation(uris, ok):
    r = APIClient().post(
        "/api/connect/oauth/register", {"client_name": "Claude", "redirect_uris": uris}, format="json"
    )
    assert (r.status_code == 201) is ok, r.data
    if ok:
        assert r.data["client_id"].startswith("aasan_c_") and r.data["token_endpoint_auth_method"] == "none"
    else:
        assert r.data["error"] == "invalid_redirect_uri"


def test_dcr_metadata_validation_and_name_cleaning():
    assert register(grant_types=["client_credentials"]).data["error"] == "invalid_client_metadata"
    assert register(response_types=["token"]).data["error"] == "invalid_client_metadata"
    assert register(scope="org:admin admin:all").data["error"] == "invalid_client_metadata"
    r = APIClient().post(
        "/api/connect/oauth/register",
        {"client_name": "<b>Cl\x00aude</b>" + "x" * 300, "redirect_uris": [REDIRECT]},
        format="json",
    )
    assert r.status_code == 201 and "<" not in r.data["client_name"] and len(r.data["client_name"]) <= 100


def test_dcr_rate_limited():
    codes = [register().status_code for _ in range(11)]
    assert codes[:10] == [201] * 10 and codes[10] == 429


# ── Consent + code flow ───────────────────────────────────────────────


def test_consent_info_and_full_pkce_flow(admin, org):
    c, u = admin
    cid = register().data["client_id"]
    info = c.get("/api/connect/authorize/", auth_params(cid))
    assert info.status_code == 200
    cl = info.data["client"]
    assert (
        cl["name"] == "Claude"
        and cl["redirect_host"] == "claude.ai"
        and cl["redirect_uri"] == REDIRECT
        and cl["new"] is True
    )
    assert info.data["orgs"] == [{"slug": "demo-academy", "name": "Demo Academy", "role": "admin"}]
    r = approve(c, cid)
    assert r.status_code == 200
    code = code_from(r.data["redirect"])
    tok = exchange(cid, code)
    assert tok.status_code == 200 and tok["Cache-Control"] == "no-store"
    assert (
        tok.data["token_type"] == "Bearer"
        and tok.data["expires_in"] == 3600
        and tok.data["scope"] == "org:admin"
    )
    assert tok.data["access_token"].startswith("amcp_at_") and tok.data["refresh_token"].startswith(
        "amcp_rt_"
    )
    # stored hashed only
    assert not Token.objects.filter(token_hash=tok.data["access_token"]).exists()
    assert not AuthCode.objects.filter(code_hash=code).exists()
    g = Grant.objects.get()
    assert g.org == org and g.user == u and g.client.client_id == cid
    # code is single use, and replaying it revokes what it issued
    again = exchange(cid, code)
    assert again.status_code == 400 and again.data["error"] == "invalid_grant"
    g.refresh_from_db()
    assert g.revoked_at and g.revoked_reason == "code_reuse"
    assert mcp(tok.data["access_token"], INIT).status_code == 401


def test_deny_redirects_with_access_denied(admin):
    c, _ = admin
    cid = register().data["client_id"]
    r = c.post(
        "/api/connect/authorize/",
        {**auth_params(cid), "org": "demo-academy", "decision": "deny"},
        format="json",
    )
    q = parse_qs(urlsplit(r.data["redirect"]).query)
    assert q["error"] == ["access_denied"] and q["state"] == ["xyz"]
    assert not AuthCode.objects.exists()


def test_authorize_validation(admin):
    c, _ = admin
    cid = register().data["client_id"]
    assert c.get("/api/connect/authorize/", auth_params("nope")).data == {"code": "invalid_client"}
    assert c.get("/api/connect/authorize/", auth_params(cid, redirect_uri="https://evil.test/cb")).data == {
        "code": "invalid_redirect_uri"
    }
    r = c.get("/api/connect/authorize/", auth_params(cid, code_challenge_method="plain"))
    assert (
        r.status_code == 400 and r.data["code"] == "invalid_request" and "redirect" not in r.data
    )  # never an automatic bounce
    assert r.data["redirect_host"] == "claude.ai" and r.data["return_url"].startswith(
        REDIRECT + "?error=invalid_request"
    )
    assert (
        c.get("/api/connect/authorize/", auth_params(cid, code_challenge=None)).data["code"]
        == "invalid_request"
    )
    assert (
        c.get("/api/connect/authorize/", auth_params(cid, scope="org:admin email")).data["code"]
        == "invalid_scope"
    )
    assert (
        c.get("/api/connect/authorize/", auth_params(cid, response_type="token")).data["code"]
        == "unsupported_response_type"
    )
    assert (
        c.get("/api/connect/authorize/", auth_params(cid, resource="https://other.test/mcp")).data["code"]
        == "invalid_target"
    )
    assert (
        APIClient().get("/api/connect/authorize/", auth_params(cid)).status_code == 401
    )  # must be signed in


def test_wrong_verifier_refused_and_burns_code(admin):
    c, _ = admin
    cid = register().data["client_id"]
    code = code_from(approve(c, cid).data["redirect"])
    bad = exchange(cid, code, verifier="w" * 50)
    assert bad.status_code == 400 and bad.data["error"] == "invalid_grant"
    assert exchange(cid, code).status_code == 400  # single use, even after a failed try
    code2 = code_from(approve(c, cid).data["redirect"])
    assert exchange(cid, code2, verifier="short").status_code == 400


def test_code_bound_to_client_redirect_and_expiry(admin):
    c, _ = admin
    cid = register().data["client_id"]
    other = register().data["client_id"]
    code = code_from(approve(c, cid).data["redirect"])
    assert exchange(other, code).data["error"] == "invalid_grant"
    code = code_from(approve(c, cid).data["redirect"])
    assert exchange(cid, code, redirect_uri="https://claude.ai/other").data["error"] == "invalid_grant"
    code = code_from(approve(c, cid).data["redirect"])
    AuthCode.objects.filter(used_at__isnull=True).update(expires_at=timezone.now() - timedelta(seconds=1))
    r = exchange(cid, code)
    assert r.status_code == 400 and r.data["error"] == "invalid_grant"
    assert exchange("unknown", code).status_code == 401
    assert (
        form("/api/connect/oauth/token", {"grant_type": "password", "client_id": cid}).data["error"]
        == "unsupported_grant_type"
    )


def test_non_admins_cannot_approve(org, auth):
    cid = register().data["client_id"]
    mgr, _ = member(org, "mgr@mcp.test", "manager")
    unit_mgr, _ = member(org, "unit@mcp.test", "manager", unit_scoped=True)
    learner, _ = member(org, "kid@mcp.test", "learner")
    for c in (mgr, unit_mgr, learner):
        assert approve(c, cid).status_code == 403
        assert c.get("/api/connect/authorize/", auth_params(cid)).data["orgs"] == []
    plain, _ = auth
    assert approve(plain, cid).status_code == 404
    other = Organization.objects.create(name="Other", slug="other")
    oc, _ = member(other, "o@mcp.test", "owner")
    assert approve(oc, cid, org="demo-academy").status_code == 404
    assert not AuthCode.objects.exists()


def test_owner_can_approve(org):
    c, _ = member(org, "owner@mcp.test", "owner")
    cid, tok = connect(c)
    assert Grant.objects.get().org == org


# ── Refresh rotation + reuse detection ────────────────────────────────


def test_refresh_rotation_and_reuse_revokes_family(admin):
    c, _ = admin
    cid, tok = connect(c)
    r1 = refresh(cid, tok["refresh_token"])
    assert r1.status_code == 200 and r1.data["refresh_token"] != tok["refresh_token"]
    assert mcp(r1.data["access_token"], INIT).status_code == 200
    assert (
        refresh(register().data["client_id"], r1.data["refresh_token"]).data["error"] == "invalid_grant"
    )  # other client
    reuse = refresh(cid, tok["refresh_token"])  # the rotated-out token comes back
    assert reuse.status_code == 400 and reuse.data["error"] == "invalid_grant"
    g = Grant.objects.get()
    assert g.revoked_at and g.revoked_reason == "refresh_reuse"
    assert refresh(cid, r1.data["refresh_token"]).status_code == 400  # the whole family is dead
    assert mcp(r1.data["access_token"], INIT).status_code == 401


def test_expired_tokens(admin):
    c, _ = admin
    cid, tok = connect(c)
    Token.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    r = mcp(tok["access_token"], INIT)
    assert r.status_code == 401 and 'error="invalid_token"' in r["WWW-Authenticate"]
    assert refresh(cid, tok["refresh_token"]).data["error"] == "invalid_grant"


def test_revocation_endpoint(admin):
    c, _ = admin
    cid, tok = connect(c)
    assert form("/api/connect/oauth/revoke", {"client_id": cid}).status_code == 400
    assert (
        form("/api/connect/oauth/revoke", {"token": "amcp_at_unknown", "client_id": cid}).status_code == 200
    )
    assert (
        form("/api/connect/oauth/revoke", {"token": tok["refresh_token"], "client_id": cid}).status_code
        == 200
    )
    assert Grant.objects.get().revoked_at is not None
    assert mcp(tok["access_token"], INIT).status_code == 401


# ── Token scope ───────────────────────────────────────────────────────


def test_token_refused_on_normal_api_and_jwt_refused_on_mcp(admin, auth):
    c, _ = admin
    _, tok = connect(c)
    other = APIClient()
    other.credentials(HTTP_AUTHORIZATION=f"Bearer {tok['access_token']}")
    for path in ("/api/users/me/", "/api/orgs/", "/api/orgs/demo-academy/members/", "/api/connect/me/"):
        assert other.get(path).status_code == 401, path
    plain, data = auth
    r = mcp(data["access"], INIT)
    assert r.status_code == 401 and 'error="invalid_token"' in r["WWW-Authenticate"]


def test_mcp_requires_bearer_with_resource_metadata():
    r = mcp(None, INIT)
    assert r.status_code == 401
    assert r["WWW-Authenticate"].startswith(
        'Bearer resource_metadata="http://localhost:5173/api/.well-known/oauth-protected-resource"'
    )
    assert APIClient().get("/api/mcp").status_code == 401


def test_demoted_admin_loses_connection(admin, org):
    c, u = admin
    _, tok = connect(c)
    Membership.objects.filter(user=u).update(role="manager")
    assert mcp(tok["access_token"], INIT).status_code == 401
    assert Grant.objects.get().revoked_reason == "role_lost"


# ── JSON-RPC ──────────────────────────────────────────────────────────


@pytest.fixture
def token(admin):
    return connect(admin[0])[1]["access_token"]


def test_initialize_ping_and_notifications(token):
    r = mcp(token, INIT)
    assert r.status_code == 200 and r["Content-Type"] == "application/json"
    res = r.json()["result"]
    assert res["protocolVersion"] == "2025-06-18" and res["capabilities"] == {"tools": {"listChanged": False}}
    assert res["serverInfo"]["name"] == "aasan"
    old = mcp(token, {**INIT, "params": {**INIT["params"], "protocolVersion": "2025-03-26"}}).json()["result"]
    assert old["protocolVersion"] == "2025-03-26"
    assert (
        mcp(token, {**INIT, "params": {"protocolVersion": "1999-01-01"}}).json()["result"]["protocolVersion"]
        == "2025-06-18"
    )
    assert mcp(token, {"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert mcp(token, {"jsonrpc": "2.0", "id": "p1", "method": "ping"}).json() == {
        "jsonrpc": "2.0",
        "id": "p1",
        "result": {},
    }
    assert mcp(token, {"jsonrpc": "2.0", "id": 3, "result": {}}).status_code == 202  # a client response


def test_jsonrpc_errors(token):
    r = mcp(token, b"{not json")
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700 and r.json()["id"] is None
    assert mcp(token, {"id": 1, "method": "ping"}).json()["error"]["code"] == -32600
    assert mcp(token, {"jsonrpc": "2.0", "id": {"x": 1}, "method": "ping"}).json()["error"]["code"] == -32600
    assert (
        mcp(token, {"jsonrpc": "2.0", "id": 2, "method": "resources/list"}).json()["error"]["code"] == -32601
    )
    assert (
        mcp(token, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": []}).json()["error"]["code"]
        == -32602
    )
    assert mcp(token, []).json()["error"]["code"] == -32600
    batch = mcp(
        token,
        [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ],
    ).json()
    assert batch == [{"jsonrpc": "2.0", "id": 1, "result": {}}]
    unknown = mcp(
        token, {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "drop_tables"}}
    ).json()
    assert unknown["error"]["code"] == -32602
    bad = mcp(
        token,
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "assignment_progress", "arguments": {}},
        },
    ).json()
    assert bad["error"]["code"] == -32602 and "assignment_id" in bad["error"]["message"]
    extra = call_raw(token, "list_members", {"page": 1, "evil": True})
    assert extra["error"]["code"] == -32602
    assert call_raw(token, "list_members", {"page": "1"})["error"]["code"] == -32602
    assert call_raw(token, "list_members", {"role": "god"})["error"]["code"] == -32602


def call_raw(token, name, args):
    return mcp(
        token,
        {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args}},
    ).json()


def test_transport_guards(token):
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert c.get("/api/mcp").status_code == 405
    assert c.delete("/api/mcp").status_code == 405
    assert mcp(token, INIT, HTTP_ORIGIN="https://evil.example").status_code == 403
    assert mcp(token, INIT, HTTP_ORIGIN="https://claude.ai").status_code == 200
    assert mcp(token, INIT, HTTP_ORIGIN="http://localhost:5173").status_code == 200
    assert (
        mcp(
            token, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, HTTP_MCP_PROTOCOL_VERSION="2024-01-01"
        ).status_code
        == 400
    )
    assert (
        mcp(
            token, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, HTTP_MCP_PROTOCOL_VERSION="2025-06-18"
        ).status_code
        == 200
    )


# ── Tools ─────────────────────────────────────────────────────────────


@pytest.fixture
def world(org, admin):
    """A course (template + assigned), learners with progress, a survey with answers — plus another org's data."""
    _, u = admin
    cur = Curriculum.objects.create(
        owner=u,
        kind="authored",
        goal="Fractions",
        title="Fractions Fun",
        status="ready",
        published_at=timezone.now(),
        template_scope="org",
        template_org=org,
    )
    sec = Section.objects.create(curriculum=cur, order=0, title="Basics")
    sub = Subsection.objects.create(
        section=sec,
        order=0,
        title="What is a fraction",
        objective="Name parts",
        lesson_status="ready",
        key_points=["Top is numerator"],
    )
    Activity.objects.create(
        subsection=sub,
        order=0,
        type="quiz",
        title="Pick one",
        payload={"options": ["a", "b"]},
        key={"correct": [1], "secret": "ANSWER-KEY-XYZ"},
    )
    _, kid = member(org, "kid@world.test", "learner")
    kid.profile.display_name = "Kavya"
    kid.profile.save()
    a = Assignment.objects.create(org=org, curriculum=cur, created_by=u)
    s = Survey.objects.create(
        org=org,
        title="Feedback",
        status="open",
        questions=[
            {"id": "q1", "type": "rating", "text": "Useful?"},
            {"id": "q2", "type": "text", "text": "Improve?"},
        ],
        anonymous=False,
    )
    SurveyResponse.objects.create(
        survey=s, respondent_key="k1", user=kid, answers={"q1": 4, "q2": "More games"}
    )
    other = Organization.objects.create(name="Other", slug="other")
    ocur = Curriculum.objects.create(
        owner=u, kind="authored", goal="x", title="Other course", template_scope="org", template_org=other
    )
    oa = Assignment.objects.create(org=other, curriculum=ocur)
    os_ = Survey.objects.create(org=other, title="Other survey", questions=[])
    return {"cur": cur, "a": a, "s": s, "kid": kid, "ocur": ocur, "oa": oa, "os": os_}


def sc(res):
    assert res["result"]["isError"] is False, res
    assert json.loads(res["result"]["content"][0]["text"]) == res["result"]["structuredContent"]
    return res["result"]["structuredContent"]


def test_tools_list(token):
    tools = mcp(token, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "org_overview",
        "list_members",
        "list_assignments",
        "assignment_progress",
        "list_courses",
        "get_course_outline",
        "list_surveys",
        "survey_results",
        "create_guest_lesson",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object" and t["description"]
    assert (
        next(t for t in tools if t["name"] == "create_guest_lesson")["annotations"]["readOnlyHint"] is False
    )


def test_tools_happy_paths(token, world, org):
    ov = sc(call(token, "org_overview"))
    assert (
        ov["org"]["slug"] == "demo-academy"
        and ov["members"] == 2
        and ov["learners"] == 1
        and ov["assignments"] == 1
    )
    assert "active_learners_this_week" in ov and "completion_pct" in ov

    mem = sc(call(token, "list_members", {"page_size": 1}))
    assert mem["total"] == 2 and mem["pages"] == 2 and len(mem["members"]) == 1
    everyone = sc(call(token, "list_members", {"role": "learner"}))["members"]
    assert [m["name"] for m in everyone] == ["<user_content>Kavya</user_content>"]  # user text is fenced
    assert "@" not in json.dumps(sc(call(token, "list_members")))  # no emails anywhere

    asg = sc(call(token, "list_assignments"))["assignments"]
    assert (
        asg[0]["assignment_id"] == world["a"].id
        and asg[0]["title"] == "<user_content>Fractions Fun</user_content>"
        and asg[0]["learners"] == 1
    )
    prog = sc(call(token, "assignment_progress", {"assignment_id": world["a"].id}))
    assert (
        prog["learner_rows"][0]["name"] == "<user_content>Kavya</user_content>"
        and prog["learner_rows"][0]["lessons_total"] == 1
    )

    courses = sc(call(token, "list_courses"))["courses"]
    assert [(c["course_id"], c["source"]) for c in courses] == [(world["cur"].id, "template+assigned")]
    outline = sc(call(token, "get_course_outline", {"course_id": world["cur"].id}))
    assert outline["sections"][0]["lessons"][0]["activities"] == [
        {"type": "quiz", "title": "<user_content>Pick one</user_content>"}
    ]
    assert "ANSWER-KEY-XYZ" not in json.dumps(outline) and "options" not in json.dumps(outline)

    surveys = sc(call(token, "list_surveys"))["surveys"]
    assert surveys[0]["survey_id"] == world["s"].id and surveys[0]["responses"] == 1
    res = sc(call(token, "survey_results", {"survey_id": world["s"].id}))
    assert res["responses"] == 1 and res["questions"][0]["avg"] == 4
    assert res["questions"][1]["answers"] == ["<user_content>More games</user_content>"]
    assert "Kavya" not in json.dumps(res)  # no respondent identities even for a named survey


def test_cross_org_refused(token, world):
    for name, args in (
        ("assignment_progress", {"assignment_id": world["oa"].id}),
        ("get_course_outline", {"course_id": world["ocur"].id}),
        ("survey_results", {"survey_id": world["os"].id}),
    ):
        res = call(token, name, args)["result"]
        assert res["isError"] is True and "No " in res["content"][0]["text"], name
    names = json.dumps(sc(call(token, "list_courses"))) + json.dumps(sc(call(token, "list_surveys")))
    assert "Other" not in names


def test_create_guest_lesson(token, admin, org, settings):
    settings.CONNECT_GUEST_LESSONS_PER_DAY = 2
    out = sc(
        call(
            token,
            "create_guest_lesson",
            {"topic": "Saving money with UPI", "audience": "college students", "language": "en"},
        )
    )
    assert out["guest_url"].startswith("http://localhost:5173/g/")
    link = GuestLink.objects.get()
    assert link.org == org and link.owner == admin[1] and link.max_uses == 50 and link.state() == "ok"
    cur = link.course
    assert cur.published_at and cur.visibility == "link"
    acts = Activity.objects.filter(subsection__section__curriculum=cur)
    assert acts.count() == 2 and all(a.type in ("quiz", "sequencing") for a in acts)  # open_input dropped
    assert all(a.key for a in acts) and "correct" not in json.dumps(out)
    sc(call(token, "create_guest_lesson", {"topic": "Second"}))
    capped = call(token, "create_guest_lesson", {"topic": "Third"})["result"]
    assert capped["isError"] is True and "2 guest lessons a day" in capped["content"][0]["text"]
    assert GuestLink.objects.count() == 2
    assert ConnectAuditLog.objects.filter(tool="create_guest_lesson", ok=False, error="daily_limit").exists()


def test_create_guest_lesson_plan_limit(token, monkeypatch):
    from apps.billing import services

    def deny(user, key, adding=1):
        raise services.PlanLimit(key, 5, 5, "free")

    monkeypatch.setattr(services, "check", deny)
    res = call(token, "create_guest_lesson", {"topic": "Anything"})["result"]
    assert res["isError"] is True and not GuestLink.objects.exists()


# ── Audit + admin screens ─────────────────────────────────────────────


def test_audit_rows_and_admin_screens(admin, world, org):
    c, u = admin
    cid, tok = connect(c)
    call(tok["access_token"], "org_overview")
    call(tok["access_token"], "assignment_progress", {"assignment_id": world["a"].id})
    call(tok["access_token"], "survey_results", {"survey_id": world["os"].id})
    assert list(
        ConnectAuditLog.objects.exclude(event="tool").order_by("id").values_list("event", flat=True)
    ) == ["approve", "code_exchange"]
    rows = list(ConnectAuditLog.objects.filter(event="tool").order_by("id"))
    assert [(r.tool, r.ok) for r in rows] == [
        ("org_overview", True),
        ("assignment_progress", True),
        ("survey_results", False),
    ]
    assert (
        rows[1].args_summary == f"assignment_id={world['a'].id}"
        and rows[0].client_name == "Claude"
        and rows[0].user == u
    )
    assert rows[2].error == "not_found" and all(r.org == org for r in rows)

    me = c.get("/api/connect/me/").data
    assert me["server_url"] == "http://localhost:5173/api/mcp" and me["orgs"][0]["slug"] == "demo-academy"
    clients = c.get("/api/connect/orgs/demo-academy/clients/").data
    assert (
        len(clients) == 1
        and clients[0]["client_name"] == "Claude"
        and clients[0]["redirect_hosts"] == ["claude.ai"]
    )
    assert clients[0]["calls"] == 3 and clients[0]["last_used_at"]
    log = c.get("/api/connect/orgs/demo-academy/audit/").data
    assert (
        log["total"] == 5 and log["rows"][0]["tool"] == "survey_results" and log["rows"][0]["event"] == "tool"
    )

    mgr, _ = member(org, "mgr2@mcp.test", "manager")
    assert mgr.get("/api/connect/orgs/demo-academy/clients/").status_code == 403
    assert mgr.get("/api/connect/orgs/demo-academy/audit/").status_code == 403
    assert mgr.get("/api/connect/me/").status_code == 403
    oc, _ = member(Organization.objects.get(slug="other"), "o2@mcp.test", "owner")
    assert oc.get("/api/connect/orgs/demo-academy/clients/").status_code == 404
    gid = clients[0]["id"]
    assert oc.delete(f"/api/connect/orgs/other/clients/{gid}/").status_code == 404  # another org's connection

    assert c.delete(f"/api/connect/orgs/demo-academy/clients/{gid}/").status_code == 204
    assert ConnectAuditLog.objects.filter(event="revoke", user=u, org=org).count() == 1
    assert c.get("/api/connect/orgs/demo-academy/clients/").data == []
    assert mcp(tok["access_token"], INIT).status_code == 401
    assert refresh(cid, tok["refresh_token"]).status_code == 400


def test_clients_without_grants_are_pruned():
    old = OAuthClient.objects.create(name="Old", redirect_uris=[REDIRECT])
    OAuthClient.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
    register()
    assert not OAuthClient.objects.filter(pk=old.pk).exists()


# ── Security review regressions ───────────────────────────────────────


def test_authorize_errors_never_auto_redirect(admin):
    c, _ = admin
    cid = register(redirect_uris=("https://evil.example/phish",)).data["client_id"]
    r = c.get(
        "/api/connect/authorize/",
        {**auth_params(cid, redirect_uri="https://evil.example/phish"), "code_challenge": "x"},
    )
    assert r.status_code == 400 and "redirect" not in r.data and r.data["redirect_host"] == "evil.example"
    r = c.post(
        "/api/connect/authorize/",
        {
            **auth_params(cid, redirect_uri="https://evil.example/phish", scope="all"),
            "decision": "approve",
            "org": "demo-academy",
        },
        format="json",
    )
    assert r.status_code == 400 and "redirect" not in r.data
    bad = c.get("/api/connect/authorize/", auth_params(cid, redirect_uri="https://other.example/cb"))
    assert bad.data == {"code": "invalid_redirect_uri"}  # no link at all


def test_homograph_hosts_rejected_and_names_cleaned():
    r = APIClient().post(
        "/api/connect/oauth/register",
        {"client_name": "Claude", "redirect_uris": ["https://\u0441laude.ai/cb"]},
        format="json",
    )
    assert r.status_code == 400 and r.data["error"] == "invalid_redirect_uri"
    r = APIClient().post(
        "/api/connect/oauth/register",
        {"client_name": "Cla\u202eude\u200b \n\t  Desktop\u2066", "redirect_uris": [REDIRECT]},
        format="json",
    )
    assert r.data["client_name"] == "Claude Desktop"


def test_old_client_not_flagged_new(admin):
    c, _ = admin
    cid = register().data["client_id"]
    OAuthClient.objects.filter(client_id=cid).update(created_at=timezone.now() - timedelta(days=2))
    assert c.get("/api/connect/authorize/", auth_params(cid)).data["client"]["new"] is False


def test_registration_limits_per_ipv6_prefix_and_ceiling(settings):
    a = APIClient(REMOTE_ADDR="2001:db8::1")
    b = APIClient(REMOTE_ADDR="2001:db8::ffff")
    body = {"client_name": "x", "redirect_uris": [REDIRECT]}
    codes = [a.post("/api/connect/oauth/register", body, format="json").status_code for _ in range(10)]
    assert codes == [201] * 10
    assert b.post("/api/connect/oauth/register", body, format="json").status_code == 429  # same /64
    assert (
        APIClient(REMOTE_ADDR="2001:db9::1")
        .post("/api/connect/oauth/register", body, format="json")
        .status_code
        == 201
    )
    settings.CONNECT_REGISTRATIONS_CEILING_PER_DAY = 0
    assert (
        APIClient(REMOTE_ADDR="10.0.0.9").post("/api/connect/oauth/register", body, format="json").status_code
        == 429
    )


def test_batches_limited_and_counted(token, monkeypatch):
    from apps.connect import mcp as mcp_mod

    six = [
        {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": "list_courses"}}
        for i in range(6)
    ]
    assert mcp(token, six).status_code == 400
    assert (
        mcp(token, six[:2], HTTP_MCP_PROTOCOL_VERSION="2025-06-18").status_code == 400
    )  # no batching in 2025-06-18
    monkeypatch.setattr(mcp_mod, "PER_MINUTE", 7)
    assert len(mcp(token, six[:5]).json()) == 5  # 5 units
    assert mcp(token, six[:3]).status_code == 429  # 5 + 3 > 7
    assert ConnectAuditLog.objects.filter(event="tool").count() == 5


def test_deep_nesting_is_parse_error(token):
    r = mcp(token, ("[" * 100000 + "]" * 100000).encode())
    assert r.status_code == 400 and r.json()["error"]["code"] == -32700


def test_connection_events_audited(admin, org):
    c, u = admin
    cid = register().data["client_id"]
    c.post(
        "/api/connect/authorize/",
        {**auth_params(cid), "org": "demo-academy", "decision": "deny"},
        format="json",
    )
    cid, tok = connect(c)
    r1 = refresh(cid, tok["refresh_token"])
    refresh(cid, tok["refresh_token"])  # reuse → family revoked
    events = list(ConnectAuditLog.objects.order_by("id").values_list("event", flat=True))
    assert events == ["deny", "approve", "code_exchange", "refresh_reuse"]
    cid2, tok2 = connect(c)
    Membership.objects.filter(user=u).update(role="manager")
    assert mcp(tok2["access_token"], INIT).status_code == 401
    assert ConnectAuditLog.objects.filter(event="role_lost").count() == 1
    assert r1.status_code == 200


def test_token_requires_redirect_uri_and_matching_resource(admin):
    c, _ = admin
    cid = register().data["client_id"]
    code = code_from(approve(c, cid).data["redirect"])
    r = form(
        "/api/connect/oauth/token",
        {"grant_type": "authorization_code", "code": code, "client_id": cid, "code_verifier": VERIFIER},
    )
    assert r.data["error"] == "invalid_grant"  # redirect_uri was in the request → required
    code = code_from(approve(c, cid).data["redirect"])
    assert exchange(cid, code, resource="http://localhost:5173/api/mcp/").status_code == 200
    code = code_from(approve(c, cid, redirect_uri=None).data["redirect"])  # single registered URI, omitted
    r = form(
        "/api/connect/oauth/token",
        {"grant_type": "authorization_code", "code": code, "client_id": cid, "code_verifier": VERIFIER},
    )
    assert r.status_code == 200
