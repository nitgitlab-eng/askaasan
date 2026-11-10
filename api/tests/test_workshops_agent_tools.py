"""Agent builder: the Aasan Tools registry and our own MCP endpoint (POST /api/workshops/mcp/)."""

import json
import time
from datetime import UTC, datetime

import pytest
from django.core import signing

from apps.accounts.models import User
from apps.workshops import mcp_server, services
from apps.workshops import tools as T
from apps.workshops.models import Workshop, WorkshopEvent, WorkshopSession
from tests.workshop_agent_helpers import agent_session

pytestmark = pytest.mark.django_db
URL = "/api/workshops/mcp/"


def ctx():
    from apps.workshops.content import seed

    seed()
    return T.Ctx(workshop=Workshop.objects.get(slug="ai-agentic"))


# ── calculator ───────────────────────────────────────────────────────


def test_calculator_basic_maths():
    assert T.call("calculator", {"expression": "2450 * 18 / 100"}, T.Ctx())["result"] == 441
    assert T.calculate("(2 + 3) ** 2 - 10 // 3 % 2") == 24
    assert T.calculate("-5 + sqrt(16) + round(2.567, 2)") == pytest.approx(1.57)
    assert T.calculate("max(1, 9, 3) + min(4, 2) + abs(-3) + floor(2.7) + ceil(2.1)") == 19
    assert T.calculate("log10(1000) + ln(e)") == 4
    assert T.calculate("2 × 3 ÷ 4") == 1.5
    assert T.calculate("2^3") == 8


@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('ls')",
        "os",
        "x + 1",
        "(1).__class__",
        "open('/etc/passwd')",
        "[1, 2]",
        "'a' * 3",
        "lambda: 1",
        "9 ** 9 ** 9",
        "2 ** 1000",
        "10 ** 101",
        "1 / 0",
        "5 % 0",
        "sqrt(-1)",
        "1e308 * 10",
        "True + 1",
        "round(1.5, ndigits=1)",
        "1" * 201,
        "",
    ],
)
def test_calculator_refuses_unsafe_or_huge(expr):
    with pytest.raises(T.ToolError):
        T.calculate(expr)


def test_calculator_input_length_and_schema():
    with pytest.raises(T.ToolError, match="Invalid arguments"):
        T.call("calculator", {"expression": "1+" * 101}, T.Ctx())
    with pytest.raises(T.ToolError, match="unknown argument"):
        T.call("calculator", {"expression": "1", "evil": 1}, T.Ctx())
    with pytest.raises(T.ToolError, match="missing"):
        T.call("calculator", {}, T.Ctx())
    with pytest.raises(T.ToolError, match="Unknown tool"):
        T.call("shell", {}, T.Ctx())


# ── units, datetime, notes, word_count ───────────────────────────────


def test_units():
    assert T.call("units", {"value": 5, "from": "km", "to": "miles"}, T.Ctx())["result"] == pytest.approx(
        3.106856
    )
    assert T.call("units", {"value": 100, "from": "C", "to": "F"}, T.Ctx())["result"] == 212
    assert T.call("units", {"value": 1, "from": "GB", "to": "MB"}, T.Ctx())["result"] == 1024
    assert T.call("units", {"value": 1, "from": "hectare", "to": "sq m"}, T.Ctx())["result"] == 10000
    assert T.call("units", {"value": 36, "from": "km/h", "to": "m/s"}, T.Ctx())["result"] == 10
    with pytest.raises(T.ToolError, match="Can't convert"):
        T.call("units", {"value": 1, "from": "kg", "to": "km"}, T.Ctx())
    with pytest.raises(T.ToolError, match="Unknown unit"):
        T.call("units", {"value": 1, "from": "parsec", "to": "km"}, T.Ctx())
    with pytest.raises(T.ToolError, match="number"):
        T.call("units", {"value": "5", "from": "km", "to": "m"}, T.Ctx())


def test_datetime(monkeypatch):
    monkeypatch.setattr(services, "now", lambda: datetime(2026, 10, 18, 6, 0, tzinfo=UTC))
    out = T.call("datetime", {"action": "now"}, T.Ctx())
    assert out["datetime"].startswith("2026-10-18T11:30") and out["tz"] == "Asia/Kolkata"
    conv = T.call(
        "datetime",
        {
            "action": "convert",
            "datetime": "2026-10-18T09:00",
            "from_tz": "Asia/Kolkata",
            "to_tz": "Europe/London",
        },
        T.Ctx(),
    )
    assert conv["to"].startswith("2026-10-18T04:30")
    assert (
        T.call("datetime", {"action": "add_days", "date": "2026-12-30", "days": 3}, T.Ctx())["date"]
        == "2027-01-02"
    )
    assert T.call("datetime", {"action": "weekday", "date": "2026-12-25"}, T.Ctx())["weekday"] == "Friday"
    with pytest.raises(T.ToolError, match="time zone"):
        T.call("datetime", {"action": "now", "tz": "../../etc/passwd"}, T.Ctx())
    with pytest.raises(T.ToolError):
        T.call("datetime", {"action": "weekday", "date": "not-a-date"}, T.Ctx())
    with pytest.raises(T.ToolError, match="Invalid arguments"):
        T.call("datetime", {"action": "add_days", "date": "2026-01-01", "days": 10**9}, T.Ctx())


def test_workshop_notes_searches_agenda_only():
    out = T.call("workshop_notes", {"query": "agent loop think act observe"}, ctx())
    assert 1 <= len(out["results"]) <= 3
    assert all(len(r["snippet"]) <= 600 for r in out["results"])
    assert any("loop" in r["snippet"].lower() for r in out["results"])
    # final MCQ options are never searchable
    out = T.call("workshop_notes", {"query": "chatbot nicer design"}, ctx())
    assert all("A chatbot with a nicer design" not in r["snippet"] for r in out["results"])


def test_word_count():
    out = T.call("word_count", {"text": "Hello world. This is Aasan! Ready?"}, T.Ctx())
    assert out["words"] == 6 and out["sentences"] == 3 and out["characters"] == 34
    with pytest.raises(T.ToolError):
        T.call("word_count", {"text": "x" * 10_001}, T.Ctx())


# ── Our MCP endpoint ─────────────────────────────────────────────────


def _rpc(client, token, msg, **headers):
    return client.post(
        URL,
        data=json.dumps(msg),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {token}",
        **headers,
    )


@pytest.fixture
def mcp(auth):
    client, _ = auth
    s = agent_session(User.objects.get(email="kavya@example.com"))
    token, _ = mcp_server.issue_token(s)
    client.credentials()  # the MCP endpoint never looks at the JWT
    return client, s, token


def test_mcp_initialize_list_call(mcp):
    client, s, token = mcp
    r = _rpc(
        client,
        token,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    )
    assert r.status_code == 200
    assert r.json()["result"]["protocolVersion"] == "2025-06-18"
    assert r.json()["result"]["capabilities"]["tools"] == {"listChanged": False}
    assert _rpc(client, token, {"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    assert _rpc(client, token, {"jsonrpc": "2.0", "id": 2, "method": "ping"}).json()["result"] == {}
    tools = _rpc(
        client,
        token,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        HTTP_MCP_PROTOCOL_VERSION="2025-06-18",
    )
    names = [t["name"] for t in tools.json()["result"]["tools"]]
    assert names == ["calculator", "workshop_notes", "datetime", "units", "word_count"]
    assert all(t["inputSchema"]["type"] == "object" for t in tools.json()["result"]["tools"])
    out = _rpc(
        client,
        token,
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "calculator", "arguments": {"expression": "6*7"}},
        },
    ).json()["result"]
    assert out["isError"] is False and out["structuredContent"]["result"] == 42
    bad = _rpc(
        client,
        token,
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "calculator", "arguments": {"expression": "__import__('os')"}},
        },
    ).json()["result"]
    assert bad["isError"] is True
    assert (
        _rpc(
            client, token, {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "nope"}}
        ).json()["error"]["code"]
        == -32602
    )
    assert (
        _rpc(client, token, {"jsonrpc": "2.0", "id": 7, "method": "resources/list"}).json()["error"]["code"]
        == -32601
    )
    ev = WorkshopEvent.objects.filter(session=s, type="agent_tool_call")
    assert [e.data for e in ev] == [{"tool": "calculator", "source": "mcp"}] * 2  # name only, never arguments


def test_mcp_protocol_guards(mcp):
    client, _, token = mcp
    batch = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
    assert _rpc(client, token, batch).status_code == 400  # no batching
    assert (
        _rpc(
            client,
            token,
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            HTTP_MCP_PROTOCOL_VERSION="1999-01-01",
        ).status_code
        == 400
    )
    r = client.post(
        URL, data=b"{not json", content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}"
    )
    assert r.json()["error"]["code"] == -32700
    assert client.get(URL, HTTP_AUTHORIZATION=f"Bearer {token}").status_code == 405
    big = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * (mcp_server.MAX_BODY + 10)}}
    assert _rpc(client, token, big).status_code == 413  # body cap
    assert (
        _rpc(
            client, token, {"jsonrpc": "2.0", "id": 1, "method": "ping"}, HTTP_ORIGIN="https://evil.example"
        ).status_code
        == 403
    )


def test_mcp_rate_limit(mcp, monkeypatch):
    client, _, token = mcp
    monkeypatch.setattr(mcp_server, "PER_MINUTE", 3)
    codes = [_rpc(client, token, {"jsonrpc": "2.0", "id": i, "method": "ping"}).status_code for i in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]


def test_mcp_token_auth_refusals(mcp, auth):
    client, s, token = mcp
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert _rpc(client, token, ping).status_code == 200
    assert (
        client.post(URL, data=json.dumps(ping), content_type="application/json").status_code == 401
    )  # no token
    # a normal Aasan JWT
    jwt = auth[1]["access"]
    assert _rpc(client, jwt, ping).status_code == 401
    # a Connect OAuth access token shape
    assert _rpc(client, "amcp_at_" + "x" * 40, ping).status_code == 401
    # tampered signature / wrong scope / wrong salt
    assert _rpc(client, token[:-3] + "abc", ping).status_code == 401
    payload = {
        "s": s.id,
        "u": s.user_id,
        "n": s.agent["mcp"]["nonce"],
        "x": s.agent["mcp"]["exp"],
        "scope": "other",
    }
    assert _rpc(client, "awt_" + signing.dumps(payload, salt=mcp_server.TOKEN_SALT), ping).status_code == 401
    payload["scope"] = mcp_server.SCOPE
    assert _rpc(client, "awt_" + signing.dumps(payload, salt="something.else"), ping).status_code == 401
    # wrong session or wrong user
    other_user = User.objects.create_user(email="arun@example.com", password="x")
    other = agent_session(other_user)
    assert (
        _rpc(
            client, "awt_" + signing.dumps({**payload, "s": other.id}, salt=mcp_server.TOKEN_SALT), ping
        ).status_code
        == 401
    )
    assert (
        _rpc(
            client, "awt_" + signing.dumps({**payload, "u": other_user.id}, salt=mcp_server.TOKEN_SALT), ping
        ).status_code
        == 401
    )
    # expired (past exp)
    stale = {**payload, "x": int(time.time()) - 5}
    s.agent["mcp"]["exp"] = stale["x"]
    WorkshopSession.objects.filter(pk=s.pk).update(agent=s.agent)
    assert _rpc(client, "awt_" + signing.dumps(stale, salt=mcp_server.TOKEN_SALT), ping).status_code == 401


def test_mcp_token_expires_on_submit_and_after_24h(mcp, monkeypatch):
    client, s, token = mcp
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 24 * 3600 + 5)
    assert _rpc(client, token, ping).status_code == 401  # past max_age / exp
    monkeypatch.setattr(time, "time", real)
    assert _rpc(client, token, ping).status_code == 200
    WorkshopSession.objects.filter(pk=s.pk).update(status=WorkshopSession.Status.SUBMITTED)
    assert _rpc(client, token, ping).status_code == 401


def test_workshop_token_is_not_a_jwt_elsewhere(mcp):
    client, _, token = mcp
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    assert client.get("/api/workshops/runs/").status_code == 401
