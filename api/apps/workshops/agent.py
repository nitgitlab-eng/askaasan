"""The workshop agent builder: the learner's agent config, their own MCP servers, and the server-side agent loop.

s.agent (JSON on WorkshopSession) = {name, role, starter, aasan_tools: [name], enabled: {"<server id>": [tool]},
auto_approve: {"<server id>": [tool]}, saved_at, runs, chat: [{role, text}], run: <paused run> | None,
mcp: {nonce, exp}}. Learner servers (with their encrypted tokens) are WorkshopAgentServer rows.

The loop: each model call (router → complete_json_sync, any provider incl. the fake one) returns an AgentStep; tools
run here (Aasan tools directly, external ones over MCP), and their results go back to the model fenced as data. At
most MAX_STEPS model calls per message and MAX_CALLS_PER_STEP tool calls per step; every model call is charged to the
session budget. An external tool call pauses the run for the learner's approval unless they chose "always allow" for
that tool; Aasan tools never need approval. Final-assessment agent tests use Aasan tools only."""

import json
import logging
import math
import re
import secrets
import time

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import mcp_client, services
from . import tools as T
from .models import WorkshopAgentServer

log = logging.getLogger(__name__)

MAX_STEPS = 5
MAX_CALLS_PER_STEP = 3
AGENT_MAX_TOKENS = 700
JUDGE_MAX_TOKENS = 400
MAX_SERVERS = 3
MAX_TOOLS = 8
NAME_MAX, ROLE_MAX, STARTER_MAX, MESSAGE_MAX, LABEL_MAX, URL_MAX, TOKEN_MAX = (
    40,
    2000,
    300,
    1000,
    40,
    500,
    2000,
)
HISTORY = 6  # earlier test-chat entries sent with each message
TRACE_TEXT_MAX = 1000  # what the browser sees of one tool result
ARGS_MAX = 4000  # JSON size of one external call's arguments
EXT_NAME = re.compile(r"^ext_(\d{1,10})__([A-Za-z0-9_.-]{1,64})$")
DENIED = "The learner did not allow this tool call. Continue without it."


class AgentRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── Config ───────────────────────────────────────────────────────────


def has_builder(workshop) -> bool:
    return any(st.get("kind") == "agent_build" for st in workshop.agenda or [])


def external_allowed(user) -> bool:
    """The platform setting and the learner's org feature switch (`external_mcp`); Aasan tools always work."""
    from apps.orgs.extras import blocked

    return bool(settings.WORKSHOP_EXTERNAL_MCP) and not blocked(user, "external_mcp")


def cfg(s) -> dict:
    a = s.agent or {}
    return {
        "name": a.get("name", ""),
        "role": a.get("role", ""),
        "starter": a.get("starter", ""),
        "aasan_tools": [n for n in a.get("aasan_tools", []) if n in T.TOOLS],
        "enabled": a.get("enabled") or {},
        "auto_approve": a.get("auto_approve") or {},
        "runs": int(a.get("runs") or 0),
        "chat": a.get("chat") or [],
        "run": a.get("run"),
        "saved_at": a.get("saved_at"),
    }


def _update(session_id, **fields) -> dict:
    """Merge keys into s.agent under the row lock (other keys, e.g. the MCP token nonce, are kept)."""
    with transaction.atomic():
        s = services.locked(session_id)
        s.agent = {**(s.agent or {}), **fields}
        s.save(update_fields=["agent"])
        return s.agent


def runs_left(s) -> int:
    return max(0, settings.WORKSHOP_AGENT_RUNS - cfg(s)["runs"])


def server_out(srv: WorkshopAgentServer, enabled: list[str]) -> dict:
    out = {
        "id": srv.id,
        "label": srv.label,
        "url": srv.url,
        "has_token": bool(srv.token_enc),  # the token itself never leaves the server
        "status": srv.status,
        "tools": [
            {"name": t["name"], "description": t["description"], "enabled": t["name"] in enabled}
            for t in srv.tools or []
        ],
    }
    if srv.error:
        out["error"] = srv.error
    return out


def agent_out(s) -> dict:
    from apps.connect.oauth import base_url

    from .mcp_server import issue_token

    c = cfg(s)
    servers = list(WorkshopAgentServer.objects.filter(session=s))
    token, expires = issue_token(s)
    pending = (c["run"] or {}).get("pending")
    return {
        "name": c["name"],
        "role": c["role"],
        "starter": c["starter"],
        "aasan_tools": [
            {
                "name": n,
                "title": t["title"],
                "description": t["description"],
                "enabled": n in c["aasan_tools"],
            }
            for n, t in T.TOOLS.items()
        ],
        "servers": [server_out(srv, c["enabled"].get(str(srv.id), [])) for srv in servers],
        "auto_approve": {k: v for k, v in c["auto_approve"].items() if v},
        "runs_left": runs_left(s),
        "external_enabled": external_allowed(s.user),
        "limits": {
            "servers": MAX_SERVERS,
            "tools": MAX_TOOLS,
            "steps": MAX_STEPS,
            "runs": settings.WORKSHOP_AGENT_RUNS,
        },
        "saved": bool(c["saved_at"]),
        "chat": c["chat"],
        "pending": pending,
        "mcp": {"url": base_url() + "/api/workshops/mcp/", "token": token, "expires_at": expires},
    }


def save(s, data: dict) -> None:
    """PUT agent/: {name, role, starter, aasan_tools: [name], enabled: {server_id: [tool]}, auto_approve?}.
    Raises AgentRefused(bad_field | bad_tool | unknown_server | too_many_tools)."""
    name, role, starter = (str(data.get(k) or "").strip() for k in ("name", "role", "starter"))
    if len(name) > NAME_MAX or len(role) > ROLE_MAX or len(starter) > STARTER_MAX:
        raise AgentRefused("too_long")
    aasan = data.get("aasan_tools") or []
    if not isinstance(aasan, list) or any(n not in T.TOOLS for n in aasan):
        raise AgentRefused("bad_tool")
    servers = {str(srv.id): srv for srv in WorkshopAgentServer.objects.filter(session=s)}
    enabled = _tool_map(data.get("enabled") or {}, servers)
    auto = data.get("auto_approve")
    auto = _tool_map(auto, servers) if auto is not None else cfg(s)["auto_approve"]
    auto = {k: [t for t in v if t in enabled.get(k, [])] for k, v in auto.items()}
    if len(set(aasan)) + sum(len(v) for v in enabled.values()) > MAX_TOOLS:
        raise AgentRefused("too_many_tools")
    _update(
        s.id,
        name=name,
        role=role,
        starter=starter,
        aasan_tools=list(dict.fromkeys(aasan)),
        enabled=enabled,
        auto_approve={k: v for k, v in auto.items() if v},
        saved_at=timezone.now().isoformat(),
    )


def _tool_map(raw, servers: dict) -> dict:
    if not isinstance(raw, dict):
        raise AgentRefused("bad_tool")
    out = {}
    for sid, names in raw.items():
        srv = servers.get(str(sid))
        if not srv:
            raise AgentRefused("unknown_server")
        known = {t["name"] for t in srv.tools or []}
        if not isinstance(names, list) or any(not isinstance(n, str) or n not in known for n in names):
            raise AgentRefused("bad_tool")
        if names:
            out[str(srv.id)] = list(dict.fromkeys(names))
    return out


# ── Learner MCP servers ──────────────────────────────────────────────


def _rate_limiter(user_id: int):
    """Per learner per minute, every external MCP HTTP request (connect, refresh and tool calls)."""

    def check():
        key = f"ws-ext-rate:{user_id}:{int(time.time() // 60)}"
        cache.add(key, 0, 120)
        try:
            n = cache.incr(key)
        except ValueError:
            cache.set(key, 1, 120)
            n = 1
        if n > settings.WORKSHOP_EXTERNAL_PER_MIN:
            raise mcp_client.McpError("rate_limited")

    return check


def _token(srv: WorkshopAgentServer) -> str:
    from apps.providers import crypto

    return crypto.decrypt(srv.token_enc) if srv.token_enc else ""


def add_server(s, url: str, label: str, token: str) -> WorkshopAgentServer:
    """Connect (initialize + tools/list) and save. Raises AgentRefused with the API error code."""
    from apps.providers import crypto

    if not external_allowed(s.user):
        raise AgentRefused("external_off")
    if WorkshopAgentServer.objects.filter(session=s).count() >= MAX_SERVERS:
        raise AgentRefused("too_many_servers")
    url = (url or "").strip()
    if not url or len(url) > URL_MAX:
        raise AgentRefused("bad_url")
    token = (token or "").strip()
    if len(token) > TOKEN_MAX or any(c in token for c in "\r\n\x00"):
        raise AgentRefused("bad_token")
    try:
        _, tools = mcp_client.connect(url, token, _rate_limiter(s.user_id))
    except mcp_client.McpError as e:
        services.event(s, "mcp_connect", ok=False, code=e.code)
        raise AgentRefused(e.code) from None
    from urllib.parse import urlsplit

    label = mcp_client.clean_text(label, LABEL_MAX) or (urlsplit(url).hostname or "")[:LABEL_MAX]
    srv = WorkshopAgentServer.objects.create(
        session=s,
        label=label,
        url=url,
        token_enc=crypto.encrypt(token) if token else "",
        tools=tools,
        status="connected",
        refreshed_at=timezone.now(),
    )
    services.event(s, "mcp_connect", ok=True, tools=len(tools))
    return srv


def refresh_server(s, srv: WorkshopAgentServer) -> None:
    if not external_allowed(s.user):
        raise AgentRefused("external_off")
    try:
        _, tools = mcp_client.connect(srv.url, _token(srv), _rate_limiter(s.user_id))
    except mcp_client.McpError as e:
        srv.status, srv.error = "error", e.code
        srv.save(update_fields=["status", "error"])
        services.event(s, "mcp_connect", ok=False, code=e.code, refresh=True)
        return
    srv.tools, srv.status, srv.error, srv.refreshed_at = tools, "connected", "", timezone.now()
    srv.save(update_fields=["tools", "status", "error", "refreshed_at"])
    names = {t["name"] for t in tools}
    c = cfg(s)
    key = str(srv.id)
    _update(
        s.id,
        enabled={**c["enabled"], key: [n for n in c["enabled"].get(key, []) if n in names]},
        auto_approve={**c["auto_approve"], key: [n for n in c["auto_approve"].get(key, []) if n in names]},
    )
    services.event(s, "mcp_connect", ok=True, tools=len(tools), refresh=True)


def delete_server(s, srv: WorkshopAgentServer) -> None:
    key = str(srv.id)
    srv.delete()
    c = cfg(services.load(s.id))
    _update(
        s.id,
        enabled={k: v for k, v in c["enabled"].items() if k != key},
        auto_approve={k: v for k, v in c["auto_approve"].items() if k != key},
    )


def wipe_secrets(session_id) -> None:
    """On submit: the learner's server tokens are deleted (the rows stay, without a token)."""
    WorkshopAgentServer.objects.filter(session_id=session_id).exclude(token_enc="").update(token_enc="")


# ── The loop ─────────────────────────────────────────────────────────


def _specs(s, c: dict, final: bool) -> dict:
    """Namespaced tool name → spec. External tools appear only outside the final, when allowed and enabled."""
    out = {}
    for n in c["aasan_tools"]:
        t = T.TOOLS[n]
        out[n] = {"name": n, "description": t["description"], "schema": t["inputSchema"], "external": False}
    if final or not external_allowed(s.user):
        return out
    for srv in WorkshopAgentServer.objects.filter(session=s, status="connected"):
        on = set(c["enabled"].get(str(srv.id), []))
        for t in srv.tools or []:
            if t["name"] in on:
                ns = f"ext_{srv.id}__{t['name']}"
                out[ns] = {
                    "name": ns,
                    "description": t["description"],
                    "schema": t["input_schema"],
                    "external": True,
                    "server": srv,
                    "tool": t["name"],
                }
    return out


def _model_step(system: str, user: str):
    from llm.prompts.workshop import AgentStep
    from llm.structured import complete_json_sync

    return complete_json_sync("tutor", system, user, AgentStep, max_tokens=AGENT_MAX_TOKENS)


def _parse_args(raw) -> dict | None:
    if isinstance(raw, dict):
        return raw
    try:
        v = json.loads(raw or "{}")
    except (ValueError, TypeError, RecursionError):
        return None
    return v if isinstance(v, dict) else None


def _clip(text: str) -> dict:
    return {"text": text[:TRACE_TEXT_MAX], "truncated": len(text) > TRACE_TEXT_MAX}


def _run_aasan(s, name: str, args: dict) -> tuple[str, bool]:
    try:
        data = T.call(name, args, T.Ctx(workshop=s.run.workshop))
    except T.ToolError as e:
        return f"Error: {e.message}", True
    except Exception:
        log.exception("workshop agent tool %s failed", name)
        return "Error: the tool failed.", True
    return json.dumps(data, ensure_ascii=False, default=str), False


def _run_external(s, spec: dict, args: dict) -> tuple[str, bool]:
    srv = spec["server"]
    try:
        if len(json.dumps(args)) > ARGS_MAX:
            return "Error: the arguments are too large.", True
        text, is_error = mcp_client.call(srv.url, _token(srv), spec["tool"], args, _rate_limiter(s.user_id))
    except mcp_client.McpError as e:
        return f"Error: the tool's server could not be used ({e.code}).", True
    except Exception:  # noqa: BLE001 — an external server must never break the run
        # never the token or the arguments in the log
        log.warning("workshop agent: external tool call failed (server %s)", srv.id)
        return "Error: the tool's server could not be used.", True
    return text or "(empty result)", is_error


def _execute(s, specs: dict, call: dict, run: dict) -> None:
    """Run one queued call (approved or not needing approval) and record the result."""
    spec = specs.get(call["name"])
    args = call["arguments"]
    if call.get("denied"):
        text, is_error = DENIED, True
    elif not spec:
        text, is_error = f"Error: there is no tool called {call['name'][:80]}.", True
    elif args is None:
        text, is_error = "Error: the arguments were not a JSON object.", True
    elif spec["external"]:
        text, is_error = _run_external(s, spec, args)
        services.event(s, "agent_tool_call", tool=spec["tool"], source="external")
    else:
        text, is_error = _run_aasan(s, spec["name"], args)
        services.event(s, "agent_tool_call", tool=spec["name"], source="aasan")
    text = text[: mcp_client.RESULT_MAX]
    run["steps"][-1]["calls"].append({"name": call["name"], "arguments": args or {}, "result": text})
    run["trace"].append(
        {
            "type": "tool_result",
            "call_id": call["call_id"],
            "tool": call["name"],
            "is_error": is_error,
            **_clip(text),
        }
    )
    if spec and not is_error:
        run.setdefault("tools_used", []).append(call["name"])


def _drive(s, c: dict, run: dict, specs: dict, final: bool) -> None:
    """Advance a run until it answers, fails, hits a limit, or pauses for approval (run["pending"] set)."""
    from llm.prompts.workshop import AGENT_SYSTEM, agent_user

    while True:
        while run["queue"]:
            call = run["queue"][0]
            spec = specs.get(call["name"])
            if (
                spec
                and spec["external"]
                and not call.get("approved")
                and not call.get("denied")
                and call["tool"] not in c["auto_approve"].get(str(spec["server"].id), [])
            ):
                run["pending"] = {
                    "call_id": call["call_id"],
                    "server": spec["server"].label,
                    "server_id": spec["server"].id,
                    "tool": spec["tool"],
                    "arguments": call["arguments"] or {},
                }
                run["trace"].append({"type": "approval_needed", **run["pending"]})
                return
            run["queue"].pop(0)
            _execute(s, specs, call, run)
        if run.get("done"):
            return
        if len(run["steps"]) >= MAX_STEPS:
            run["trace"].append({"type": "error", "code": "step_limit"})
            run["done"] = True
            return
        if reason := services.spend(s.id, AGENT_MAX_TOKENS, exempt=final):
            run["trace"].append({"type": "error", "code": reason})
            run["done"] = True
            return
        user = agent_user(
            c["name"],
            c["role"],
            list(specs.values()),
            [] if final else c["chat"][-HISTORY:],
            run["message"],
            run["steps"],
        )
        try:
            step = _model_step(AGENT_SYSTEM, user)
        except Exception:
            log.exception("workshop agent step failed for session %s", s.id)
            run["trace"].append({"type": "error", "code": "agent_unavailable"})
            run["done"] = True
            return
        thought = " ".join((step.thought or "").split())[:500]
        if thought:
            run["trace"].append({"type": "thought", "text": thought})
        calls = list(step.tool_calls or [])
        if not calls:
            answer = (step.answer or "").strip()[:4000]
            run["answer"] = answer
            run["trace"].append({"type": "answer", "text": answer})
            run["done"] = True
            return
        if len(calls) > MAX_CALLS_PER_STEP:
            run["trace"].append({"type": "error", "code": "too_many_tool_calls", "kept": MAX_CALLS_PER_STEP})
        run["steps"].append({"thought": thought, "calls": []})
        for tc in calls[:MAX_CALLS_PER_STEP]:
            name = str(tc.name or "")[:80]
            spec = specs.get(name)
            item = {
                "call_id": secrets.token_hex(6),
                "name": name,
                "tool": spec["tool"] if spec and spec["external"] else name,
                "arguments": _parse_args(tc.arguments),
            }
            run["queue"].append(item)
            run["trace"].append(
                {
                    "type": "tool_call",
                    "call_id": item["call_id"],
                    "tool": name,
                    "server": spec["server"].label if spec and spec["external"] else "Aasan",
                    "arguments": item["arguments"] or {},
                }
            )


def _new_run(message: str) -> dict:
    return {"message": message, "steps": [], "queue": [], "trace": [], "pending": None, "done": False}


def _out(run: dict, s) -> dict:
    out = {"trace": run["trace"], "done": bool(run.get("done")), "runs_left": runs_left(s)}
    if run.get("pending"):
        out["pending"] = run["pending"]
    return out


def _finish(session_id, run: dict) -> dict:
    """Store a paused run, or file a finished one into the test chat."""
    s = services.load(session_id)
    c = cfg(s)
    if run.get("pending"):
        return _update(session_id, run=_storable(run))
    chat = c["chat"] + [{"role": "user", "text": run["message"]}]
    if run.get("answer"):
        chat.append({"role": "agent", "text": run["answer"]})
    return _update(session_id, run=None, chat=chat[-2 * HISTORY :])


def _storable(run: dict) -> dict:
    return json.loads(json.dumps(run, default=str))


def run_message(s, message: str) -> dict:
    """POST agent/run/. Raises AgentRefused(runs_exhausted | too_long | empty)."""
    message = (message or "").strip()
    if not message:
        raise AgentRefused("empty")
    if len(message) > MESSAGE_MAX:
        raise AgentRefused("too_long")
    with transaction.atomic():
        locked = services.locked(s.id)
        c = cfg(locked)
        if c["runs"] >= settings.WORKSHOP_AGENT_RUNS:
            raise AgentRefused("runs_exhausted")
        locked.agent = {
            **(locked.agent or {}),
            "runs": c["runs"] + 1,
            "run": None,
        }  # a new message drops a pause
        locked.save(update_fields=["agent"])
        services.event(locked, "build_test", chars=len(message))
    s = services.load(s.id)
    c = cfg(s)
    run = _new_run(message)
    _drive(s, c, run, _specs(s, c, final=False), final=False)
    _finish(s.id, run)
    return _out(run, services.load(s.id))


def approve(s, call_id: str, decision: str) -> dict:
    """POST agent/approve/: approve | deny | always (always also allows this tool for the rest of the session)."""
    c = cfg(s)
    run = c["run"]
    if not run or not run.get("pending"):
        raise AgentRefused("no_pending")
    pending = run["pending"]
    if call_id != pending["call_id"]:
        raise AgentRefused("bad_call")
    call = run["queue"][0]
    if decision == "deny":
        call["denied"] = True
    else:
        call["approved"] = True
    if decision == "always":
        key = str(pending["server_id"])
        auto = {
            **c["auto_approve"],
            key: list(dict.fromkeys([*c["auto_approve"].get(key, []), pending["tool"]])),
        }
        _update(s.id, auto_approve=auto)
        c["auto_approve"] = auto
    run["trace"].append({"type": "approval", "call_id": call_id, "decision": decision})
    run["pending"] = None
    _drive(s, c, run, _specs(s, c, final=False), final=False)
    _finish(s.id, run)
    return _out(run, services.load(s.id))


def reset(s) -> None:
    _update(s.id, chat=[], run=None)


# ── Final: hidden agent tests ────────────────────────────────────────

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
VALUE_MAX_NUMBERS = 5


def value_ok(answer: str, expected, tolerance=None) -> bool:
    """Does the answer contain the expected value? Numbers match within `tolerance` (default 1%, at least 0.5)."""
    exp = str(expected).replace(",", "").strip()
    try:
        target = float(exp)
    except ValueError:
        return exp.lower() in (answer or "").lower()
    tol = float(tolerance) if tolerance is not None else max(0.5, abs(target) * 0.01)
    nums = _NUM.findall((answer or "").replace(",", ""))
    # The answer's last number is its result; spraying many numbers to hit the target never passes.
    if not nums or len(nums) > VALUE_MAX_NUMBERS:
        return False
    try:
        return abs(float(nums[-1]) - target) <= tol
    except ValueError:
        return False


def _scrub(text: str, test: dict) -> str:
    """Judge feedback without the hidden test's question or expected value (even if the judge was talked into it)."""
    for secret in (str(test.get("q") or "").strip(), str(test.get("expected") or "").strip()):
        if secret:
            text = re.sub(re.escape(secret), "…", text, flags=re.IGNORECASE)
    return text


def _judge(test: dict, run: dict) -> tuple[float | None, str]:
    from llm.prompts.workshop import AGENT_JUDGE_SYSTEM, AgentJudge, agent_judge_user
    from llm.structured import complete_json_sync

    trace = "\n".join(
        f"{c['name']}({json.dumps(c['arguments'], ensure_ascii=False)[:300]}) → {c['result'][:500]}"
        for st in run["steps"]
        for c in st["calls"]
    )
    try:
        j = complete_json_sync(
            "tutor",
            AGENT_JUDGE_SYSTEM,
            agent_judge_user(
                str(test.get("q", "")),
                [str(r) for r in test.get("rubric", [])],
                str(test.get("expected", "")),
                trace or "(no tool calls)",
                run.get("answer") or "",
            ),
            AgentJudge,
            max_tokens=JUDGE_MAX_TOKENS,
        )
    except Exception:
        log.exception("workshop agent judge failed")
        return None, ""
    raw = float(j.score)
    return (min(1.0, max(0.0, raw)) if math.isfinite(raw) else 0.0), " ".join(j.feedback.split())[:300]


def grade_agent_tests(s) -> tuple[float, list[dict]] | None:
    """Run the saved agent on the workshop's hidden `final.agent_tests` (Aasan tools only, no approvals, no test
    chat history) → (score 0..1, per-test summary), or None when the workshop has no agent tests. The questions and
    expected values are never returned."""
    tests = (s.run.workshop.final or {}).get("agent_tests") or []
    if not tests:
        return None
    c = cfg(s)
    if not c["saved_at"]:
        return 0.0, [
            {
                "index": i,
                "label": mcp_client.clean_text(t.get("label"), 80),
                "score": 0.0,
                "passed": False,
                "tools_used": [],
                "feedback": "No saved agent.",
            }
            for i, t in enumerate(tests)
        ]
    specs = _specs(s, c, final=True)
    summary = []
    for i, test in enumerate(tests):
        run = _new_run(str(test.get("q", ""))[:MESSAGE_MAX])
        _drive(s, c, run, specs, final=True)
        used = list(dict.fromkeys(run.get("tools_used", [])))
        expect = [t for t in test.get("expect_tools", []) if isinstance(t, str)]
        tool_ok = all(t in used for t in expect)
        has_value = test.get("expected") not in (None, "")
        v_ok = (
            value_ok(run.get("answer") or "", test["expected"], test.get("tolerance")) if has_value else None
        )
        services.spend(s.id, JUDGE_MAX_TOKENS, exempt=True)
        judged, feedback = _judge(test, run)
        parts = [] if judged is None else [(judged, 0.5)]
        parts.append((1.0 if tool_ok else 0.0, 0.25))
        if v_ok is not None:
            parts.append((1.0 if v_ok else 0.0, 0.25))
        score = round(sum(v * w for v, w in parts) / sum(w for _, w in parts), 3)
        summary.append(
            {
                "index": i,
                "label": mcp_client.clean_text(
                    test.get("label"), 80
                ),  # learner-safe; never the expected answer
                "score": score,
                "passed": score >= s.run.workshop.pass_mark,  # the same bar as the final
                "tools_used": used,
                "used_expected_tools": tool_ok,
                "value_ok": v_ok,
                # never the agent's raw answer: a role can make it quote the hidden question
                "feedback": _scrub(feedback, test),
                "error": next((t["code"] for t in run["trace"] if t["type"] == "error"), None),
            }
        )
    total = round(sum(t["score"] for t in summary) / len(summary), 3)
    return total, summary
