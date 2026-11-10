import logging

import anthropic

from ..base import LLMError, LLMRequest, StreamEvent
from ..sources import clean_sources

log = logging.getLogger(__name__)

# Server-side refusal fallback ("default" routing) is available for Sonnet 5.5
# on the Claude API; Haiku has no server-side fallback.
_FALLBACK_MODELS = {"claude-sonnet-5-5", "claude-opus-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


# Newest first; older models only know the basic tool (same order as llm/research.py).
SEARCH_TOOLS = ("web_search_20260209", "web_search_20250305")
MAX_SEARCHES = 3  # per reply: enough to cross-check a fact, short enough for a voice call
MAX_CONTINUES = 1  # a paused search turn is resumed once


def search_tool(version: str) -> dict:
    from django.conf import settings

    tool = {
        "type": version,
        "name": "web_search",
        "max_uses": MAX_SEARCHES,
        "user_location": {"type": "approximate", "country": "IN", "timezone": "Asia/Kolkata"},
    }
    if settings.WEB_SEARCH_BLOCKED_DOMAINS:
        tool["blocked_domains"] = list(settings.WEB_SEARCH_BLOCKED_DOMAINS)
    return tool


def _sources(msg) -> list[dict]:
    """Cited pages first (what the reply actually relied on), then the other results."""
    cited, found = [], []
    for block in msg.content:
        if block.type == "text":
            for c in getattr(block, "citations", None) or []:
                if getattr(c, "url", None):
                    cited.append({"title": getattr(c, "title", ""), "url": c.url})
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            found += [{"title": r.title, "url": r.url} for r in block.content if getattr(r, "url", None)]
    return cited + found


def _content(m):
    if not m.images:
        return m.content
    return [
        *(
            {"type": "image", "source": {"type": "base64", "media_type": i.media_type, "data": i.data_b64}}
            for i in m.images
        ),
        {"type": "text", "text": m.content},
    ]


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    def _params(self, req: LLMRequest) -> dict:
        params = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            # Stable system prompt first, cached; per-turn content lives in messages.
            "system": [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": m.role, "content": _content(m)} for m in req.messages],
            "output_config": {"effort": req.effort},
        }
        if req.json_schema:
            params["output_config"]["format"] = {"type": "json_schema", "schema": req.json_schema}
        if req.model in _FALLBACK_MODELS:
            params["betas"] = [_FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    async def stream(self, req: LLMRequest):
        params = self._params(req)
        # Newest search tool first, then the basic one, then no search at all (a model without the tool still answers).
        tools = (*SEARCH_TOOLS, None) if req.web_search else (None,)
        usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
        sources: list[dict] = []
        try:
            for turn in range(MAX_CONTINUES + 1):
                for i, tool in enumerate(tools):
                    if tool:
                        params["tools"] = [search_tool(tool)]
                    else:
                        params.pop("tools", None)
                    try:
                        final = None
                        async with self.client.beta.messages.stream(**params) as s:
                            async for ev in s:
                                if ev.type == "text":
                                    yield StreamEvent(delta=ev.text)
                                elif (
                                    ev.type == "content_block_start"
                                    and ev.content_block.type == "server_tool_use"
                                ):
                                    yield StreamEvent(status="searching")
                            final = await s.get_final_message()
                        tools = (tool,)  # this version works: keep it for a continued turn
                        break
                    except anthropic.BadRequestError:
                        # The model doesn't know this search tool (refused before any text): try the next option.
                        if i == len(tools) - 1:
                            raise
                        log.info("web search tool %s refused; trying %s", tool, tools[i + 1])
                u = final.usage
                usage["input_tokens"] += u.input_tokens
                usage["output_tokens"] += u.output_tokens
                usage["cache_read_input_tokens"] += u.cache_read_input_tokens or 0
                sources += _sources(final)
                # A long search can pause the turn; send it back as is and the model carries on.
                if final.stop_reason != "pause_turn" or turn == MAX_CONTINUES:
                    break
                params["messages"] = [*params["messages"], {"role": "assistant", "content": final.content}]
        except anthropic.RateLimitError as e:
            raise LLMError("rate_limited", str(e), retryable=True) from e
        except anthropic.APIStatusError as e:
            raise LLMError("provider_error", e.message, retryable=e.status_code >= 500) from e
        except anthropic.APIConnectionError as e:
            raise LLMError("provider_unreachable", str(e), retryable=True) from e
        yield StreamEvent(
            done=True,
            stop_reason=final.stop_reason,
            model=final.model,
            usage=usage,
            sources=clean_sources(sources),
        )

    async def aclose(self):
        await self.client.close()

    async def complete(self, req: LLMRequest) -> str:
        chunks = []
        async for ev in self.stream(req):
            if ev.done and ev.stop_reason == "refusal":
                raise LLMError("refusal")
            chunks.append(ev.delta)
        return "".join(chunks)
