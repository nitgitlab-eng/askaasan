import openai

from ..base import LLMError, LLMRequest, StreamEvent
from ..sources import clean_sources


def _content(m):
    if not m.images:
        return m.content
    return [
        *(
            {"type": "image_url", "image_url": {"url": f"data:{i.media_type};base64,{i.data_b64}"}}
            for i in m.images
        ),
        {"type": "text", "text": m.content},
    ]


def _input(m):
    """A message for the Responses API (used when the reply may search the web)."""
    if m.role == "assistant" or not m.images:
        return {"role": m.role, "content": m.content}
    return {
        "role": "user",
        "content": [
            *(
                {"type": "input_image", "image_url": f"data:{i.media_type};base64,{i.data_b64}"}
                for i in m.images
            ),
            {"type": "input_text", "text": m.content},
        ],
    }


def _citations(response) -> list[dict]:
    out = []
    for item in getattr(response, "output", None) or []:
        for c in getattr(item, "content", None) or []:
            for a in getattr(c, "annotations", None) or []:
                if getattr(a, "type", "") == "url_citation":
                    out.append({"title": getattr(a, "title", ""), "url": a.url})
    return out


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str):
        self.client = openai.AsyncOpenAI(api_key=api_key)

    async def stream(self, req: LLMRequest):
        if req.web_search:
            said = False
            try:
                async for ev in self._stream_with_search(req):
                    said = True
                    yield ev
                return
            except LLMError as e:  # a model without web search: answer without it
                if said or e.code != "web_search_unsupported":
                    raise
        messages = [{"role": "system", "content": req.system}] + [
            {"role": m.role, "content": _content(m)} for m in req.messages
        ]
        usage, finish = {}, None
        try:
            extra = {}
            if req.json_schema:
                extra["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": req.json_schema, "strict": True},
                }
            resp = await self.client.chat.completions.create(
                model=req.model,
                messages=messages,
                max_completion_tokens=req.max_tokens,
                stream=True,
                stream_options={"include_usage": True},
                **extra,
            )
            async for chunk in resp:
                if chunk.usage:
                    usage = {
                        "input_tokens": chunk.usage.prompt_tokens,
                        "output_tokens": chunk.usage.completion_tokens,
                    }
                for choice in chunk.choices:
                    if choice.delta and choice.delta.content:
                        yield StreamEvent(delta=choice.delta.content)
                    if choice.finish_reason:
                        finish = choice.finish_reason
        except openai.RateLimitError as e:
            raise LLMError("rate_limited", str(e), retryable=True) from e
        except openai.APIConnectionError as e:
            raise LLMError("provider_unreachable", str(e), retryable=True) from e
        except openai.APIError as e:
            raise LLMError(
                "provider_error", str(e), retryable=(getattr(e, "status_code", None) or 0) >= 500
            ) from e
        yield StreamEvent(done=True, stop_reason=finish, usage=usage, model=req.model)

    async def _stream_with_search(self, req: LLMRequest):
        """The Responses API with its web_search tool: "searching" while it looks, then the reply's words."""
        response = None
        try:
            resp = await self.client.responses.create(
                model=req.model,
                instructions=req.system,
                input=[_input(m) for m in req.messages],
                tools=[
                    {
                        "type": "web_search",
                        "user_location": {"type": "approximate", "country": "IN", "timezone": "Asia/Kolkata"},
                    }
                ],
                max_output_tokens=req.max_tokens,
                stream=True,
            )
            async for ev in resp:
                kind = getattr(ev, "type", "")
                if kind == "response.output_text.delta":
                    yield StreamEvent(delta=ev.delta)
                elif kind == "response.web_search_call.in_progress":
                    yield StreamEvent(status="searching")
                elif kind in ("response.completed", "response.incomplete"):
                    response = ev.response
        except openai.BadRequestError as e:
            raise LLMError("web_search_unsupported", str(e)) from e
        except openai.RateLimitError as e:
            raise LLMError("rate_limited", str(e), retryable=True) from e
        except openai.APIConnectionError as e:
            raise LLMError("provider_unreachable", str(e), retryable=True) from e
        except openai.APIError as e:
            raise LLMError(
                "provider_error", str(e), retryable=(getattr(e, "status_code", None) or 0) >= 500
            ) from e
        u = getattr(response, "usage", None)
        incomplete = getattr(response, "status", "") == "incomplete"
        yield StreamEvent(
            done=True,
            stop_reason="max_tokens" if incomplete else "end_turn",
            usage={
                "input_tokens": getattr(u, "input_tokens", 0),
                "output_tokens": getattr(u, "output_tokens", 0),
            },
            model=req.model,
            sources=clean_sources(_citations(response)),
        )

    async def aclose(self):
        await self.client.close()

    async def complete(self, req: LLMRequest) -> str:
        return "".join([ev.delta async for ev in self.stream(req)])
