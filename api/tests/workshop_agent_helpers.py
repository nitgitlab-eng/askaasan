"""Shared fixtures for the agent builder tests: a started agentic-workshop session and a stub MCP server that
replaces apps.learning.safe_fetch.post_json (no network)."""

import json

from django.utils import timezone

from apps.learning import safe_fetch
from apps.workshops import services
from apps.workshops.content import seed
from apps.workshops.models import Workshop, WorkshopEnrollment, WorkshopRun, WorkshopSession

SECRET_TOKEN = "sk-live-SUPERSECRET-123456"


def agent_session(user, slug="ai-agentic", at_build=True):
    seed()
    run = WorkshopRun.objects.create(
        workshop=Workshop.objects.get(slug=slug), audience="public", starts_at=timezone.now(), status="live"
    )
    e = WorkshopEnrollment.objects.create(run=run, user=user)
    s = WorkshopSession.objects.create(enrollment=e, user=user, run=run)
    s.prereqs_done = {p["key"]: "x" for p in run.workshop.prerequisites}
    s.save()
    assert services.start(s) is None
    if at_build:
        s.stage_index = next(i for i, st in enumerate(run.workshop.agenda) if st["kind"] == "agent_build")
        s.save(update_fields=["stage_index"])
    return services.load(s.id)


class StubServer:
    """A Streamable HTTP MCP server double. `tools` pages, `results` per tool, `mode` json|sse; records every request."""

    def __init__(self, tools=None, mode="json", pages=1, results=None, session_id="sess-abc"):
        self.tools = (
            tools
            if tools is not None
            else [
                {
                    "name": "weather",
                    "description": "Weather for a city.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"city": {"type": "string"}},
                        "required": ["city"],
                    },
                }
            ]
        )
        self.mode, self.pages, self.session_id = mode, pages, session_id
        self.results = results or {"weather": "Sunny, 31°C"}
        self.requests: list[dict] = []
        self.status_override = None

    def _reply(self, msg_id, result):
        payload = {"jsonrpc": "2.0", "id": msg_id, "result": result}
        if self.mode == "sse":
            note = {
                "jsonrpc": "2.0",
                "method": "notifications/message",
                "params": {"level": "info", "data": "hi"},
            }
            other = {"jsonrpc": "2.0", "id": 9999, "result": {}}
            body = (
                f": keep-alive\n\nevent: message\ndata: {json.dumps(note)}\n\n"
                f"data: {json.dumps(other)}\n\ndata: {json.dumps(payload)}\n\n"
            ).encode()
            return safe_fetch.RawResponse(200, {"content-type": "text/event-stream"}, body)
        return safe_fetch.RawResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode())

    def __call__(self, url, body, headers=None, deadline=None, stop=None):
        msg = body if isinstance(body, dict) else json.loads(body)
        self.requests.append({"url": url, "msg": msg, "headers": dict(headers or {})})
        if self.status_override:
            return safe_fetch.RawResponse(self.status_override, {}, b"")
        method = msg.get("method")
        if "id" not in msg:
            return safe_fetch.RawResponse(202, {}, b"")
        if method == "initialize":
            r = self._reply(
                msg["id"],
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "stub"},
                },
            )
            r.headers["mcp-session-id"] = self.session_id
            return r
        if method == "tools/list":
            cursor = (msg.get("params") or {}).get("cursor")
            page = int(cursor or 0)
            per = max(1, -(-len(self.tools) // self.pages))
            chunk = self.tools[page * per : (page + 1) * per]
            result = {"tools": chunk}
            if page + 1 < self.pages:
                result["nextCursor"] = str(page + 1)
            return self._reply(msg["id"], result)
        if method == "tools/call":
            name = msg["params"]["name"]
            return self._reply(
                msg["id"], {"content": [{"type": "text", "text": self.results.get(name, "ok")}]}
            )
        return self._reply(msg["id"], {})
