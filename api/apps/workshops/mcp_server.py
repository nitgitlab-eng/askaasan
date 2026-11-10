"""Aasan Tools as a real MCP server: Streamable HTTP, JSON-RPC 2.0 over POST /api/workshops/mcp/, plain JSON responses.

A thin adapter over apps.workshops.tools (the same registry the internal agent loop calls directly). Mirrors
apps.connect.mcp: protocol versions, Origin check, body cap, per-token rate limit, JSON-RPC errors, and no batching.

Auth: only a per-session workshop token (`awt_…`): signed with django.core.signing under its own salt and scope,
bound to the session id, the user and a per-session nonce, and valid for at most 24 h. It dies when the session is
submitted. Normal Aasan JWTs and Connect OAuth tokens are refused here (and this token is refused everywhere else:
it isn't a JWT)."""

import json
import logging
import secrets
import time
from datetime import UTC, datetime

from django.core import signing
from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import tools as T

log = logging.getLogger(__name__)
LATEST = "2025-06-18"
SUPPORTED = (LATEST, "2025-03-26")
MAX_BODY = 64 * 1024
PER_MINUTE = 60
TOKEN_PREFIX = "awt_"
TOKEN_SALT = "apps.workshops.mcp-token"
SCOPE = "workshop-tools"
TOKEN_TTL = 24 * 60 * 60
TOKEN_MAX_LEN = 400

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32700, -32600, -32601, -32602
INSTRUCTIONS = (
    "Aasan Tools from an Aasan AI workshop: a calculator, a search over this workshop's notes, date and time "
    "helpers, a unit converter and a word counter. All are pure and safe; none reach the internet."
)


# ── Tokens ───────────────────────────────────────────────────────────


def issue_token(s) -> tuple[str, datetime]:
    """The session's current MCP token and its expiry. The nonce/expiry pair lives in s.agent["mcp"] and rotates
    once it has expired; the signed token text itself is never stored."""
    from .models import WorkshopSession

    now = int(time.time())
    mcp = (s.agent or {}).get("mcp") or {}
    if not mcp.get("nonce") or int(mcp.get("exp") or 0) <= now + 60:
        mcp = {"nonce": secrets.token_urlsafe(12), "exp": now + TOKEN_TTL}
        s.agent = {**(s.agent or {}), "mcp": mcp}
        WorkshopSession.objects.filter(pk=s.pk).update(agent=s.agent)
    payload = {"s": s.id, "u": s.user_id, "n": mcp["nonce"], "x": mcp["exp"], "scope": SCOPE}
    token = TOKEN_PREFIX + signing.dumps(payload, salt=TOKEN_SALT)
    return token, datetime.fromtimestamp(mcp["exp"], tz=UTC)


def session_for_token(raw: str):
    """→ the WorkshopSession this bearer token may use, or None."""
    from apps.orgs.extras import blocked

    from .models import WorkshopSession

    if not isinstance(raw, str) or not raw.startswith(TOKEN_PREFIX) or len(raw) > TOKEN_MAX_LEN:
        return None
    try:
        p = signing.loads(raw[len(TOKEN_PREFIX) :], salt=TOKEN_SALT, max_age=TOKEN_TTL)
    except (signing.BadSignature, ValueError, TypeError):
        return None
    if not isinstance(p, dict) or p.get("scope") != SCOPE:
        return None
    if not isinstance(p.get("x"), int) or p["x"] <= time.time():
        return None
    s = (
        WorkshopSession.objects.select_related("run__workshop", "user")
        .filter(pk=p.get("s"), user_id=p.get("u"))
        .first()
    )
    if not s or not s.user.is_active or s.status == WorkshopSession.Status.SUBMITTED or not s.started_at:
        return None
    mcp = (s.agent or {}).get("mcp") or {}
    if (
        not secrets.compare_digest(str(mcp.get("nonce") or ""), str(p.get("n") or ""))
        or mcp.get("exp") != p["x"]
    ):
        return None
    if blocked(s.user, "workshops"):
        return None
    if s.run.audience == s.run.Audience.ORG:
        from .org import in_audience

        if not in_audience(s.run, s.user):  # removed from the run's classes: the session is no longer theirs
            return None
    return s


# ── Endpoint ─────────────────────────────────────────────────────────


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _json(body, status=200) -> JsonResponse:
    resp = JsonResponse(body, status=status, safe=False)
    resp["Cache-Control"] = "no-store"
    return resp


def _valid_id(v) -> bool:
    return (isinstance(v, str) and len(v) <= 200) or (isinstance(v, int) and not isinstance(v, bool))


def _rate_ok(session_id: int) -> bool:
    key = f"ws-mcp-rate:{session_id}:{int(time.time() // 60)}"
    cache.add(key, 0, 120)
    try:
        return cache.incr(key) <= PER_MINUTE
    except ValueError:  # the counter vanished between add and incr: start over, never fail open
        cache.set(key, 1, 120)
        return True


def _allowed_origins() -> set[str]:
    from apps.connect.mcp import allowed_origins

    return allowed_origins()


@csrf_exempt
def endpoint(request):
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") not in _allowed_origins():  # DNS-rebinding / cross-site guard
        return _json(_error(None, INVALID_REQUEST, "Origin not allowed"), status=403)
    h = request.headers.get("Authorization", "")
    s = session_for_token(h[7:].strip()) if h[:7].lower() == "bearer " else None
    if not s:
        resp = _json(_error(None, INVALID_REQUEST, "Unauthorized"), status=401)
        resp["WWW-Authenticate"] = 'Bearer error="invalid_token"'
        return resp
    if request.method != "POST":  # no server-initiated SSE stream, no sessions to delete
        resp = _json(_error(None, INVALID_REQUEST, "Method not allowed"), status=405)
        resp["Allow"] = "POST"
        return resp
    pv = request.headers.get("MCP-Protocol-Version")
    if pv and pv not in SUPPORTED:
        return _json(
            _error(None, INVALID_REQUEST, f"Unsupported MCP-Protocol-Version: {pv[:40]}"), status=400
        )
    if len(request.body) > MAX_BODY:
        return _json(_error(None, INVALID_REQUEST, "Request too large"), status=413)
    if not _rate_ok(s.id):
        return _json(_error(None, INVALID_REQUEST, "Too many requests"), status=429)
    try:
        msg = json.loads(request.body or b"")
    except (ValueError, UnicodeDecodeError, RecursionError):
        return _json(_error(None, PARSE_ERROR, "Parse error"), status=400)
    if isinstance(msg, list):
        return _json(_error(None, INVALID_REQUEST, "Batching is not supported"), status=400)
    out = handle(s, msg)
    if out is None:
        return HttpResponse(status=202)  # notification or client response: accepted, no body
    status = 400 if "error" in out and out["error"]["code"] in (PARSE_ERROR, INVALID_REQUEST) else 200
    return _json(out, status=status)


def handle(s, msg) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(
            msg.get("id") if isinstance(msg, dict) and _valid_id(msg.get("id")) else None,
            INVALID_REQUEST,
            "Invalid Request",
        )
    if "method" not in msg:
        return None  # a response to something we never asked: ignore
    method, is_notification, id_ = msg["method"], "id" not in msg, msg.get("id")
    if not isinstance(method, str) or (not is_notification and not _valid_id(id_)):
        return _error(id_ if _valid_id(id_) else None, INVALID_REQUEST, "Invalid Request")
    params = msg.get("params") or {}
    if not isinstance(params, dict):
        return None if is_notification else _error(id_, INVALID_PARAMS, "params must be an object")
    if is_notification:
        return None
    if method == "initialize":
        pv = params.get("protocolVersion")
        return _result(
            id_,
            {
                "protocolVersion": pv if pv in SUPPORTED else LATEST,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aasan-tools", "title": "Aasan Tools", "version": "1.0.0"},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": T.tool_list()})
    if method == "tools/call":
        return _call(s, id_, params)
    return _error(id_, METHOD_NOT_FOUND, f"Method not found: {method[:80]}")


def _call(s, id_, params: dict) -> dict:
    from . import services

    name, args = params.get("name"), params.get("arguments") or {}
    if not isinstance(name, str) or name not in T.TOOLS:
        return _error(id_, INVALID_PARAMS, f"Unknown tool: {str(name)[:80]}")
    if problem := T.check_args(T.TOOLS[name]["inputSchema"], args):
        return _error(id_, INVALID_PARAMS, f"Invalid arguments: {problem}")
    services.event(s, "agent_tool_call", tool=name, source="mcp")  # the tool name only, never arguments
    try:
        data = T.call(name, args, T.Ctx(workshop=s.run.workshop))
    except T.ToolError as e:
        return _result(id_, {"content": [{"type": "text", "text": e.message}], "isError": True})
    except Exception:
        log.exception("workshop MCP tool %s failed", name)
        return _result(
            id_,
            {
                "content": [{"type": "text", "text": "Something went wrong. Please try again."}],
                "isError": True,
            },
        )
    data = json.loads(json.dumps(data, default=str, ensure_ascii=False))
    return _result(
        id_,
        {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "structuredContent": data,
            "isError": False,
        },
    )
