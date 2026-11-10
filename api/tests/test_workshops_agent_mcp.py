"""Agent builder: the Streamable HTTP MCP client and its SSRF-safe transport (safe_fetch.post_json). No network:
post_json is stubbed for the client tests; resolve/post_transport are stubbed for the transport tests."""

import json
import time

import pytest

from apps.learning import safe_fetch
from apps.workshops import mcp_client
from tests.workshop_agent_helpers import StubServer

URL = "https://mcp.example.com/mcp"


# ── Client: JSON and SSE, session id, protocol header, pagination ────


@pytest.mark.parametrize("mode", ["json", "sse"])
def test_connect_lists_tools_over_json_and_sse(monkeypatch, mode):
    srv = StubServer(mode=mode)
    monkeypatch.setattr(safe_fetch, "post_json", srv)
    client, tools = mcp_client.connect(URL, "tok-1")
    assert tools == [
        {
            "name": "weather",
            "description": "Weather for a city.",
            "input_schema": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]
    methods = [r["msg"].get("method") for r in srv.requests]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]
    init = srv.requests[0]
    assert init["msg"]["params"]["protocolVersion"] == "2025-06-18"
    assert init["msg"]["params"]["clientInfo"]["title"] == "Aasan"
    assert init["headers"]["Accept"] == "application/json, text/event-stream"
    assert "Mcp-Session-Id" not in init["headers"] and "MCP-Protocol-Version" not in init["headers"]
    for r in srv.requests[1:]:  # after initialize: session id and protocol version on every request
        assert r["headers"]["Mcp-Session-Id"] == "sess-abc"
        assert r["headers"]["MCP-Protocol-Version"] == "2025-06-18"
        assert r["headers"]["Authorization"] == "Bearer tok-1"
    text, is_error = client.call_tool("weather", {"city": "Chennai"})
    assert (text, is_error) == ("Sunny, 31°C", False)


def test_sse_parser_ignores_notifications_and_other_ids():
    body = (
        b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
        b'data: {"jsonrpc":"2.0","id":"srv-1","method":"sampling/createMessage","params":{}}\n\n'
        b'data: {"jsonrpc":"2.0",\ndata: "id":7,"result":{"ok":true}}\n\n'
    )
    msgs = mcp_client._sse_messages(body)
    assert mcp_client._match(msgs, 7) == {"jsonrpc": "2.0", "id": 7, "result": {"ok": True}}
    assert mcp_client._match(msgs, "srv-1") is None  # a server request is never treated as our answer


def test_pagination_follows_next_cursor_up_to_three_pages(monkeypatch):
    tools = [{"name": f"t{i}", "description": "", "inputSchema": {"type": "object"}} for i in range(8)]
    srv = StubServer(tools=tools, pages=4)
    monkeypatch.setattr(safe_fetch, "post_json", srv)
    _, got = mcp_client.connect(URL)
    lists = [r for r in srv.requests if r["msg"].get("method") == "tools/list"]
    assert len(lists) == 3  # page cap
    assert lists[1]["msg"]["params"] == {"cursor": "1"}
    assert [t["name"] for t in got] == [f"t{i}" for i in range(6)]


def test_tool_cap_and_unsafe_tools_dropped(monkeypatch):
    tools = [{"name": f"t{i}", "inputSchema": {"type": "object"}} for i in range(60)]
    tools += [
        {"name": "bad name; rm -rf", "inputSchema": {"type": "object"}},
        {"name": "x" * 65, "inputSchema": {"type": "object"}},
        {"name": "noschema"},
        {"name": "arrayschema", "inputSchema": {"type": "array"}},
        {
            "name": "huge",
            "inputSchema": {
                "type": "object",
                "properties": {"a": {"type": "string", "description": "x" * 9000}},
            },
        },
    ]
    srv = StubServer(tools=tools[::-1])
    monkeypatch.setattr(safe_fetch, "post_json", srv)
    _, got = mcp_client.connect(URL)
    assert len(got) == 50
    assert not {"bad name; rm -rf", "x" * 65, "noschema", "arrayschema", "huge"} & {t["name"] for t in got}


@pytest.mark.parametrize(
    "response",
    [
        safe_fetch.RawResponse(200, {"content-type": "text/html"}, b"<html>hi</html>"),
        safe_fetch.RawResponse(200, {"content-type": "application/json"}, b"{not json"),
        safe_fetch.RawResponse(
            200, {"content-type": "application/json"}, b'{"jsonrpc":"2.0","id":99,"result":{}}'
        ),
        safe_fetch.RawResponse(
            200,
            {"content-type": "application/json"},
            b'{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"1.0"}}',
        ),
        safe_fetch.RawResponse(
            200,
            {"content-type": "application/json"},
            b'{"jsonrpc":"2.0","id":1,"error":{"code":-1,"message":"no"}}',
        ),
        safe_fetch.RawResponse(404, {}, b""),
        safe_fetch.RawResponse(200, {"content-type": "text/event-stream"}, b"data: garbage\n\n"),
    ],
)
def test_malformed_responses_are_not_mcp(monkeypatch, response):
    monkeypatch.setattr(safe_fetch, "post_json", lambda *a, **k: response)
    with pytest.raises(mcp_client.McpError) as e:
        mcp_client.connect(URL)
    assert e.value.code == "not_mcp"


def test_auth_failure_and_server_errors(monkeypatch):
    monkeypatch.setattr(safe_fetch, "post_json", lambda *a, **k: safe_fetch.RawResponse(401, {}, b""))
    with pytest.raises(mcp_client.McpError, match="auth_failed"):
        mcp_client.connect(URL, "wrong")
    monkeypatch.setattr(safe_fetch, "post_json", lambda *a, **k: safe_fetch.RawResponse(503, {}, b""))
    with pytest.raises(mcp_client.McpError, match="unreachable"):
        mcp_client.connect(URL)


def test_custom_api_key_header():
    assert mcp_client.auth_header("X-Api-Key: abc123") == {"X-Api-Key": "abc123"}
    assert mcp_client.auth_header("abc123") == {"Authorization": "Bearer abc123"}
    assert mcp_client.auth_header("") == {}


def test_results_are_text_only_and_capped():
    text, err = mcp_client.result_text(
        {
            "content": [
                {"type": "text", "text": "A" * 5000},
                {"type": "image", "data": "...", "mimeType": "image/png"},
            ]
        }
    )
    assert len(text) == mcp_client.RESULT_MAX and not err
    text, _ = mcp_client.result_text(
        {"content": [{"type": "resource_link", "uri": "https://169.254.169.254/latest"}]}
    )
    assert text.startswith("[link:")  # named, never fetched
    text, err = mcp_client.result_text({"structuredContent": {"temp": 31}, "isError": True})
    assert json.loads(text) == {"temp": 31} and err


# ── SSRF-safe transport: safe_fetch.post_json ────────────────────────


@pytest.fixture
def net(monkeypatch):
    """resolve → a public IP unless overridden; post_transport records calls and returns `state['resp']`."""
    state = {
        "ips": ["93.184.216.34"],
        "calls": [],
        "resp": safe_fetch.RawResponse(200, {"content-type": "application/json"}, b"{}"),
    }

    def resolve(host):
        return state["ips"]

    def transport(host, ip, path, body, headers, deadline, stop=None):
        state["calls"].append(
            {"host": host, "ip": ip, "path": path, "headers": headers, "deadline": deadline}
        )
        if isinstance(state["resp"], Exception):
            raise state["resp"]
        return state["resp"]

    monkeypatch.setattr(safe_fetch, "resolve", resolve)
    monkeypatch.setattr(safe_fetch, "post_transport", transport)
    return state


def test_post_json_pins_vetted_ip_with_deadline(net):
    before = time.monotonic()
    safe_fetch.post_json(URL, {"a": 1}, {"Accept": "application/json", "Authorization": "Bearer t"})
    call = net["calls"][0]
    assert call["ip"] == "93.184.216.34" and call["host"] == "mcp.example.com" and call["path"] == "/mcp"
    assert call["deadline"] <= before + safe_fetch.POST_TIMEOUT_S + 0.5  # ≤10 s hard deadline
    assert "Cookie" not in call["headers"] and "cookie" not in {k.lower() for k in call["headers"]}


@pytest.mark.parametrize(
    "url, code",
    [
        ("http://mcp.example.com/mcp", "not_https"),
        ("https://localhost/mcp", "blocked_host"),
        ("https://127.0.0.1/mcp", "blocked_host"),
        ("https://169.254.169.254/latest/meta-data", "blocked_host"),
        ("https://[::1]/mcp", "blocked_host"),
        ("https://metadata.google.internal/x", "blocked_host"),
        ("https://user:pw@mcp.example.com/", "bad_url"),
        ("https://mcp.example.com:8080/mcp", "bad_url"),
        ("not a url", "bad_url"),
    ],
)
def test_client_refuses_unsafe_urls(net, url, code):
    with pytest.raises(mcp_client.McpError) as e:
        mcp_client.connect(url)
    assert e.value.code == code
    assert net["calls"] == []  # nothing was sent


@pytest.mark.parametrize(
    "ip", ["10.0.0.5", "192.168.1.1", "127.0.0.1", "169.254.169.254", "100.64.0.1", "::1", "fd00::1"]
)
def test_private_dns_answers_are_blocked(net, ip):
    net["ips"] = ["93.184.216.34", ip]  # one bad answer poisons the lot
    with pytest.raises(mcp_client.McpError, match="unreachable"):
        mcp_client.connect(URL)
    assert net["calls"] == []


def test_redirect_is_not_followed(net):
    net["resp"] = safe_fetch.RawResponse(302, {"location": "https://169.254.169.254/"}, b"")
    with pytest.raises(safe_fetch.FetchFailed, match="redirect"):
        safe_fetch.post_json(URL, {})
    assert len(net["calls"]) == 1
    with pytest.raises(mcp_client.McpError, match="not_mcp"):
        mcp_client.connect(URL)


def test_oversized_response_rejected(net):
    net["resp"] = safe_fetch.RawResponse(
        200, {"content-type": "application/json"}, b"x" * (safe_fetch.POST_MAX_BYTES + 1)
    )
    with pytest.raises(safe_fetch.FetchRefused, match="too_large"):
        safe_fetch.post_json(URL, {})
    net["resp"] = safe_fetch.RawResponse(200, {"content-length": str(10**7)}, b"")
    with pytest.raises(safe_fetch.FetchRefused, match="too_large"):
        safe_fetch.post_json(URL, {})
    net["resp"] = safe_fetch.RawResponse(200, {"content-encoding": "gzip"}, b"")
    with pytest.raises(safe_fetch.FetchRefused, match="encoded_body"):
        safe_fetch.post_json(URL, {})


def test_timeout_maps_to_timeout(net):
    net["resp"] = safe_fetch.FetchFailed("timeout")
    with pytest.raises(mcp_client.McpError, match="timeout"):
        mcp_client.connect(URL)


def test_request_headers_are_allow_listed(net):
    for bad in (
        {"Cookie": "a=b"},
        {"Host": "evil"},
        {"Authorization": "x\r\nX-Evil: 1"},
        {"Transfer-Encoding": "chunked"},
    ):
        with pytest.raises(safe_fetch.FetchRefused, match="bad_header"):
            safe_fetch.post_json(URL, {}, bad)
    assert net["calls"] == []
    with pytest.raises(safe_fetch.FetchRefused, match="too_large"):
        safe_fetch.post_json(URL, b"x" * (safe_fetch.POST_MAX_BODY + 1))


def test_post_transport_stops_reading_an_open_sse_stream(monkeypatch):
    """The real transport: a stub connection whose stream never ends; `stop` ends the read after our answer."""

    class Resp:
        status = 200

        def __init__(self):
            self.n = 0

        def getheaders(self):
            return [("Content-Type", "text/event-stream")]

        def read1(self, n):
            self.n += 1
            if self.n == 1:
                return b'data: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
            raise AssertionError("kept reading after the answer")

    class Conn:
        def __init__(self, host, ip, timeout):
            self.sock = object()

        def connect(self):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return Resp()

        def close(self):
            pass

    monkeypatch.setattr(safe_fetch, "_PinnedHTTPS", Conn)
    monkeypatch.setattr(safe_fetch, "_DeadlineSocket", lambda sock, deadline, cap: sock)
    stop = lambda buf: mcp_client._match(mcp_client._sse_messages(buf), 1) is not None
    r = safe_fetch.post_transport(
        "mcp.example.com", "93.184.216.34", "/mcp", b"{}", {}, time.monotonic() + 5, stop
    )
    assert r.status == 200 and b'"id":1' in r.body
