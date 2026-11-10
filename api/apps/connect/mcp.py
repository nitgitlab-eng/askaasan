"""Remote MCP server (Streamable HTTP transport): JSON-RPC 2.0 over POST /api/mcp, plain JSON responses.

Auth: OAuth access tokens from apps.connect.oauth only (normal Aasan JWTs are refused here, and these tokens are
refused everywhere else). Each request re-checks that the approving user is still an admin of the grant's org."""

import json
import logging

from django.core.cache import cache
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import ConnectAuditLog, Grant
from .oauth import SCOPE, base_url, bearer_grant, resource_metadata_url
from .tools import TOOLS, UNTRUSTED_NOTE, Ctx, ToolError, check_args, summarize_args, tool_list

log = logging.getLogger(__name__)
LATEST = "2025-06-18"
SUPPORTED = (LATEST, "2025-03-26")
MAX_BODY = 256 * 1024
MAX_BATCH = 20
MAX_BATCH_CALLS = 5  # tools/call messages per batch
PER_MINUTE = 120

PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR = (
    -32700,
    -32600,
    -32601,
    -32602,
    -32603,
)

INSTRUCTIONS = (
    "Aasan is an AI learning platform for schools, colleges and companies in India. These tools read one "
    "organisation's learning data (members, assignments, courses, surveys) for its admin, and can create a short "
    "guest demo lesson. Member data is personal: summarise, don't dump it. " + UNTRUSTED_NOTE
)


def allowed_origins() -> set[str]:
    from django.conf import settings

    extra = getattr(settings, "CONNECT_ALLOWED_ORIGINS", ["https://claude.ai", "https://claude.com"])
    return {base_url(), *[o.rstrip("/") for o in extra]}


def _error(id_, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def _result(id_, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _json(body, status=200) -> JsonResponse:
    resp = JsonResponse(body, status=status, safe=False)
    resp["Cache-Control"] = "no-store"
    return resp


def _unauthorized(reason: str) -> JsonResponse:
    resp = _json(_error(None, INVALID_REQUEST, "Unauthorized"), status=401)
    challenge = f'Bearer resource_metadata="{resource_metadata_url()}", scope="{SCOPE}"'
    if reason == "invalid":
        challenge += ', error="invalid_token", error_description="The access token is invalid or expired"'
    resp["WWW-Authenticate"] = challenge
    return resp


def _valid_id(v) -> bool:
    return (isinstance(v, str) and len(v) <= 200) or (isinstance(v, int) and not isinstance(v, bool))


def _rate_ok(grant: Grant, cost: int = 1) -> bool:
    """Per grant per minute; every tools/call in a batch costs one unit."""
    key = f"mcp-rate:{grant.id}:{int(timezone.now().timestamp() // 60)}"
    cache.add(key, 0, 120)
    try:
        return cache.incr(key, cost) <= PER_MINUTE
    except ValueError:  # the counter vanished between add and incr: start over, never fail open
        cache.set(key, cost, 120)
        return cost <= PER_MINUTE


def _calls(msgs: list) -> int:
    return sum(1 for m in msgs if isinstance(m, dict) and m.get("method") == "tools/call")


@csrf_exempt
def endpoint(request):
    origin = request.headers.get("Origin")
    if origin and origin.rstrip("/") not in allowed_origins():  # DNS-rebinding / cross-site guard
        return _json(_error(None, INVALID_REQUEST, "Origin not allowed"), status=403)
    grant, why = bearer_grant(request)
    if not grant:
        return _unauthorized(why)
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
    try:
        msg = json.loads(request.body or b"")
    except (ValueError, UnicodeDecodeError, RecursionError):  # deeply nested input must not become a 500
        return _json(_error(None, PARSE_ERROR, "Parse error"), status=400)
    batch = isinstance(msg, list)
    if batch and (pv == LATEST or not msg or len(msg) > MAX_BATCH or _calls(msg) > MAX_BATCH_CALLS):
        return _json(
            _error(None, INVALID_REQUEST, "Invalid batch"), status=400
        )  # 2025-06-18 removed batching
    if not _rate_ok(grant, max(1, _calls(msg) if batch else 1)):
        return _json(_error(None, INVALID_REQUEST, "Too many requests"), status=429)
    _touch(grant)
    ctx = Ctx(user=grant.user, org=grant.org, grant=grant)
    if batch:
        out = [r for r in (handle(ctx, m) for m in msg) if r is not None]
        return _json(out) if out else HttpResponse(status=202)
    out = handle(ctx, msg)
    if out is None:
        return HttpResponse(status=202)  # notification or client response: accepted, no body
    status = 400 if "error" in out and out["error"]["code"] in (PARSE_ERROR, INVALID_REQUEST) else 200
    return _json(out, status=status)


def _touch(grant: Grant) -> None:
    now = timezone.now()
    if not grant.last_used_at or (now - grant.last_used_at).total_seconds() > 60:
        Grant.objects.filter(pk=grant.pk).update(last_used_at=now)


def handle(ctx: Ctx, msg) -> dict | None:
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _error(
            msg.get("id") if isinstance(msg, dict) and _valid_id(msg.get("id")) else None,
            INVALID_REQUEST,
            "Invalid Request",
        )
    if "method" not in msg:
        return None  # a response to something we never asked: ignore
    method = msg["method"]
    is_notification = "id" not in msg
    id_ = msg.get("id")
    if not isinstance(method, str) or (not is_notification and not _valid_id(id_)):
        return _error(id_ if _valid_id(id_) else None, INVALID_REQUEST, "Invalid Request")
    params = msg.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return None if is_notification else _error(id_, INVALID_PARAMS, "params must be an object")
    if is_notification:
        return None  # notifications/initialized, notifications/cancelled, …: nothing to do
    if method == "initialize":
        pv = params.get("protocolVersion")
        return _result(
            id_,
            {
                "protocolVersion": pv if pv in SUPPORTED else LATEST,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "aasan", "title": "Aasan", "version": "1.0.0"},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(id_, {})
    if method == "tools/list":
        return _result(id_, {"tools": tool_list()})
    if method == "tools/call":
        return _call(ctx, id_, params)
    return _error(id_, METHOD_NOT_FOUND, f"Method not found: {method[:80]}")


def _audit(ctx: Ctx, tool: str, args, ok: bool, error: str = "") -> None:
    ConnectAuditLog.objects.create(
        event="tool",
        grant=ctx.grant,
        client_name=ctx.grant.client.name[:100],
        user=ctx.user,
        org=ctx.org,
        tool=tool[:40],
        args_summary=summarize_args(args),
        ok=ok,
        error=error[:40],
    )


def _call(ctx: Ctx, id_, params: dict) -> dict:
    name, args = params.get("name"), params.get("arguments") or {}
    tool = TOOLS.get(name) if isinstance(name, str) else None
    if not tool:
        _audit(ctx, str(name or "?")[:40], args, False, "unknown_tool")
        return _error(id_, INVALID_PARAMS, f"Unknown tool: {str(name)[:80]}")
    if problem := check_args(tool["inputSchema"], args):
        _audit(ctx, name, args, False, "invalid_arguments")
        return _error(id_, INVALID_PARAMS, f"Invalid arguments: {problem}")
    try:
        data = tool["fn"](ctx, args)
    except ToolError as e:
        _audit(ctx, name, args, False, e.code)
        return _result(id_, {"content": [{"type": "text", "text": e.message}], "isError": True})
    except Exception:
        log.exception("MCP tool %s failed", name)
        _audit(ctx, name, args, False, "internal_error")
        return _result(
            id_,
            {
                "content": [
                    {"type": "text", "text": "Something went wrong on Aasan's side. Please try again."}
                ],
                "isError": True,
            },
        )
    _audit(ctx, name, args, True)
    data = json.loads(
        json.dumps({"untrusted_content": UNTRUSTED_NOTE, **data}, default=str, ensure_ascii=False)
    )
    return _result(
        id_,
        {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "structuredContent": data,
            "isError": False,
        },
    )
