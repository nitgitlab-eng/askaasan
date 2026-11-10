"""Client side of MCP's Streamable HTTP transport, for the learner's own remote MCP servers.

Every request goes through apps.learning.safe_fetch.post_json: https only, public IPs only (re-resolved and pinned per
request), no redirects, ≤10 s, ≤256 KB, no cookies, and only the learner's own auth header is forwarded.

Everything a server sends back is untrusted: tool names must match [A-Za-z0-9_.-]{1,64}, descriptions are cut to 300
characters, input schemas must be small objects and are passed on in a sanitised form, and results are reduced to
plain text of at most 4000 characters. Nothing here ever follows a link or fetches a resource on a server's behalf."""

import json
import re
import time

from apps.learning import safe_fetch

PROTOCOL = "2025-06-18"
SUPPORTED = (PROTOCOL, "2025-03-26", "2024-11-05")
CLIENT_INFO = {"name": "aasan-workshop-agent", "title": "Aasan", "version": "1.0.0"}
MAX_PAGES = 3
MAX_TOOLS = 50
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
DESC_MAX = 300
RESULT_MAX = 4000
SCHEMA_MAX = 8 * 1024
SCHEMA_PROPS = 20
SESSION_ID_RE = re.compile(r"^[\x21-\x7e]{1,200}$")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_TYPES = ("string", "number", "integer", "boolean", "array", "object")

# safe_fetch codes → the learner-facing codes in the agent API
_REFUSED = {
    "https_only": "not_https",
    "ip_not_allowed": "blocked_host",
    "private_address": "blocked_host",
    "bad_url": "bad_url",
    "port_not_allowed": "bad_url",
    "bad_header": "bad_token",
    "too_large": "not_mcp",
    "encoded_body": "not_mcp",
}
_FAILED = {"timeout": "timeout", "redirect": "not_mcp"}


class McpError(Exception):
    """`code` is one of bad_url, not_https, blocked_host, unreachable, timeout, not_mcp, auth_failed, bad_token,
    rate_limited, session_expired."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def clean_text(value, limit: int) -> str:
    """Untrusted text → printable, whitespace-collapsed, at most `limit` characters."""
    if not isinstance(value, str):
        return ""
    return " ".join(_CTRL.sub(" ", value).split())[:limit]


def auth_header(token: str) -> dict[str, str]:
    """The learner's secret as one request header: `X-Some-Key: value` is sent as that header, anything else as
    `Authorization: Bearer <token>`."""
    token = (token or "").strip()
    if not token:
        return {}
    m = re.match(r"^(X-[A-Za-z0-9-]{1,38})\s*:\s*(\S.*)$", token)
    if m:
        return {m.group(1): m.group(2).strip()}
    return {"Authorization": f"Bearer {token}"}


def sanitize_schema(schema) -> dict | None:
    """→ a small, flat JSON Schema object, or None when the server's schema isn't acceptable."""
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return None
    try:
        if len(json.dumps(schema)) > SCHEMA_MAX:
            return None
    except (TypeError, ValueError, RecursionError):
        return None
    props_in = schema.get("properties") or {}
    if not isinstance(props_in, dict) or len(props_in) > SCHEMA_PROPS:
        return None
    props = {}
    for name, p in props_in.items():
        if not isinstance(name, str) or not NAME_RE.match(name) or not isinstance(p, dict):
            return None
        t = p.get("type")
        if isinstance(t, list):  # ["string", "null"] → "string"
            t = next((x for x in t if x in _TYPES and x != "null"), None)
        out = {"type": t if t in _TYPES else "string"}
        if desc := clean_text(p.get("description"), 200):
            out["description"] = desc
        enum = p.get("enum")
        if isinstance(enum, list) and 0 < len(enum) <= 20:
            vals = [v for v in enum if isinstance(v, str | int | float) and not isinstance(v, bool)]
            vals = [clean_text(v, 60) if isinstance(v, str) else v for v in vals]
            if vals:
                out["enum"] = vals
        if out["type"] == "array" and isinstance(p.get("items"), dict) and p["items"].get("type") in _TYPES:
            out["items"] = {"type": p["items"]["type"]}
        props[name] = out
    req = schema.get("required") or []
    required = [r for r in req if isinstance(r, str) and r in props] if isinstance(req, list) else []
    return {"type": "object", "properties": props, "required": required}


def sanitize_tool(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        return None
    schema = sanitize_schema(raw.get("inputSchema"))
    if schema is None:
        return None
    return {"name": name, "description": clean_text(raw.get("description"), DESC_MAX), "input_schema": schema}


def result_text(result) -> tuple[str, bool]:
    """A tools/call result → (plain text ≤ RESULT_MAX, is_error). Images, audio and links are named, never fetched."""
    if not isinstance(result, dict):
        raise McpError("not_mcp")
    parts = []
    content = result.get("content")
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text") or ""))
        elif kind == "resource" and isinstance(item.get("resource"), dict):
            parts.append(str(item["resource"].get("text") or "[binary resource omitted]"))
        elif kind == "resource_link":
            parts.append(f"[link: {clean_text(item.get('name') or item.get('uri'), 80)}]")
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} omitted]")
        if sum(len(p) for p in parts) > RESULT_MAX * 2:
            break
    if not parts and "structuredContent" in result:
        try:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False)[: RESULT_MAX * 2])
        except (TypeError, ValueError, RecursionError):
            pass
    text = _CTRL.sub(" ", "\n".join(parts)).strip()[:RESULT_MAX]
    return text, bool(result.get("isError"))


def _sse_messages(body: bytes) -> list:
    """JSON-RPC messages carried in an SSE stream's `data:` lines (events joined per the SSE rules)."""
    out, data = [], []
    for raw in body.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw == "":
            if data:
                try:
                    out.append(json.loads("\n".join(data)))
                except (ValueError, RecursionError):
                    pass
                data = []
            continue
        if raw.startswith(":"):
            continue
        field, _, value = raw.partition(":")
        if field == "data":
            data.append(value.removeprefix(" "))
    if data:  # a stream cut off right after the last data line
        try:
            out.append(json.loads("\n".join(data)))
        except (ValueError, RecursionError):
            pass
    return out


def _match(messages, want_id):
    for m in messages if isinstance(messages, list) else [messages]:
        if isinstance(m, dict) and m.get("id") == want_id and ("result" in m or "error" in m):
            return m
    return None  # notifications, server requests and other responses are ignored


class McpClient:
    """One MCP session with one server. `before_request` is called before every HTTP request (the per-user rate
    limit) and may raise McpError("rate_limited")."""

    def __init__(self, url: str, token: str = "", before_request=None):
        self.url = url
        self._auth = auth_header(token)
        self._before = before_request
        self.session_id: str | None = None
        self.protocol: str | None = None
        self.server_info: dict = {}
        self._next = 0

    def _headers(self) -> dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **self._auth,
        }
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _send(self, msg: dict, want_id=None):
        if self._before:
            self._before()
        stop = None
        if want_id is not None:

            def stop(buf: bytes) -> bool:  # an SSE stream may stay open after our answer: stop reading there
                return b"\n\n" in buf and _match(_sse_messages(buf), want_id) is not None

        try:
            r = safe_fetch.post_json(
                self.url, msg, self._headers(), time.monotonic() + safe_fetch.POST_TIMEOUT_S, stop
            )
        except safe_fetch.FetchRefused as e:
            raise McpError(_REFUSED.get(e.code, "not_mcp")) from None
        except safe_fetch.FetchFailed as e:
            raise McpError(_FAILED.get(e.code, "unreachable")) from None
        if r.status in (401, 403):
            raise McpError("auth_failed")
        if r.status == 404 and self.session_id:
            raise McpError("session_expired")
        if r.status >= 500:
            raise McpError("unreachable")
        if not 200 <= r.status < 300:
            raise McpError("not_mcp")
        sid = r.headers.get("mcp-session-id")
        if sid and SESSION_ID_RE.match(sid):
            self.session_id = sid
        if want_id is None:
            return None  # a notification: 202 Accepted (any 2xx is fine)
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype == "application/json":
            try:
                messages = json.loads(r.body.decode("utf-8", errors="replace"))
            except (ValueError, RecursionError):
                raise McpError("not_mcp") from None
        elif ctype == "text/event-stream":
            messages = _sse_messages(r.body)
        else:
            raise McpError("not_mcp")
        m = _match(messages, want_id)
        if m is None or m.get("jsonrpc") != "2.0":
            raise McpError("not_mcp")
        return m

    def request(self, method: str, params: dict | None = None) -> dict:
        self._next += 1
        msg = {"jsonrpc": "2.0", "id": self._next, "method": method}
        if params is not None:
            msg["params"] = params
        m = self._send(msg, self._next)
        if "error" in m:
            err = m["error"] if isinstance(m["error"], dict) else {}
            raise McpRpcError(clean_text(err.get("message"), 200) or "error")
        if not isinstance(m.get("result"), dict):
            raise McpError("not_mcp")
        return m["result"]

    def initialize(self) -> dict:
        try:
            res = self.request(
                "initialize",
                {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT_INFO},
            )
        except McpRpcError:
            raise McpError("not_mcp") from None
        pv = res.get("protocolVersion")
        if (
            not isinstance(pv, str)
            or pv not in SUPPORTED
            or not isinstance(res.get("capabilities", {}), dict)
        ):
            raise McpError("not_mcp")
        self.protocol = pv
        info = res.get("serverInfo") if isinstance(res.get("serverInfo"), dict) else {}
        self.server_info = {
            "name": clean_text(info.get("name"), 60),
            "version": clean_text(info.get("version"), 30),
        }
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def list_tools(self) -> list[dict]:
        tools, cursor, seen = [], None, set()
        for _ in range(MAX_PAGES):
            try:
                res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            except McpRpcError:
                raise McpError("not_mcp") from None
            page = res.get("tools")
            if not isinstance(page, list):
                raise McpError("not_mcp")
            for raw in page:
                t = sanitize_tool(raw)
                if t and t["name"] not in seen and len(tools) < MAX_TOOLS:
                    seen.add(t["name"])
                    tools.append(t)
            cursor = res.get("nextCursor")
            if not isinstance(cursor, str) or not cursor or len(cursor) > 500 or len(tools) >= MAX_TOOLS:
                break
        return tools

    def call_tool(self, name: str, arguments: dict) -> tuple[str, bool]:
        try:
            res = self.request("tools/call", {"name": name, "arguments": arguments})
        except McpRpcError as e:
            return f"Tool error: {e.message}", True
        return result_text(res)


class McpRpcError(Exception):
    """A JSON-RPC error object from the server (its message is untrusted, cleaned text)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def check_url(url: str) -> None:
    """Fail fast on an unsafe URL shape before any request (post_json re-checks and vets the IPs on every call)."""
    try:
        safe_fetch.check_url(url)
    except safe_fetch.FetchRefused as e:
        raise McpError(_REFUSED.get(e.code, "bad_url")) from None


def connect(url: str, token: str = "", before_request=None) -> tuple[McpClient, list[dict]]:
    """initialize → notifications/initialized → tools/list. Raises McpError."""
    check_url(url)
    c = McpClient(url, token, before_request)
    c.initialize()
    return c, c.list_tools()


def call(url: str, token: str, name: str, arguments: dict, before_request=None) -> tuple[str, bool]:
    """A fresh session for one tools/call (re-initialising once if the server dropped the session)."""
    check_url(url)
    c = McpClient(url, token, before_request)
    c.initialize()
    try:
        return c.call_tool(name, arguments)
    except McpError as e:
        if e.code != "session_expired":
            raise
    c = McpClient(url, token, before_request)
    c.initialize()
    return c.call_tool(name, arguments)
