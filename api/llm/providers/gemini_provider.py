import base64

from google import genai
from google.genai import types

from ..base import LLMError, LLMRequest, StreamEvent
from ..sources import clean_sources


def _finish_reason(chunk) -> str | None:
    """The chunk's finish reason in the shared vocabulary: "max_tokens" when the output limit cut the reply off,
    "end_turn" for any other finish, None while the reply is still streaming."""
    for cand in getattr(chunk, "candidates", None) or []:
        fr = getattr(cand, "finish_reason", None)
        if fr:
            name = str(getattr(fr, "name", None) or fr).upper()
            return "max_tokens" if "MAX_TOKENS" in name else "end_turn"
    return None


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str):
        self.client = genai.Client(api_key=api_key)

    async def stream(self, req: LLMRequest):
        contents = [
            types.Content(
                role="user" if m.role == "user" else "model",
                parts=[
                    *(
                        types.Part.from_bytes(data=base64.b64decode(i.data_b64), mime_type=i.media_type)
                        for i in m.images
                    ),
                    types.Part(text=m.content),
                ],
            )
            for m in req.messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=req.system,
            max_output_tokens=req.max_tokens,
            response_mime_type="application/json" if req.json_schema else None,
            # Google Search grounding: Gemini decides itself whether to search (it gives no "searching" signal).
            tools=[types.Tool(google_search=types.GoogleSearch())] if req.web_search else None,
        )
        usage = {}
        stop = "end_turn"
        sources: list[dict] = []
        try:
            async for chunk in await self.client.aio.models.generate_content_stream(
                model=req.model, contents=contents, config=config
            ):
                if chunk.text:
                    yield StreamEvent(delta=chunk.text)
                if reason := _finish_reason(chunk):
                    stop = reason
                for cand in getattr(chunk, "candidates", None) or []:
                    gm = getattr(cand, "grounding_metadata", None)
                    for ch in getattr(gm, "grounding_chunks", None) or []:
                        if getattr(ch, "web", None):
                            sources.append({"title": ch.web.title, "url": ch.web.uri})
                if chunk.usage_metadata:
                    usage = {
                        "input_tokens": chunk.usage_metadata.prompt_token_count or 0,
                        "output_tokens": chunk.usage_metadata.candidates_token_count or 0,
                    }
        except Exception as e:  # google-genai surfaces several error types
            code = getattr(e, "code", 0)
            retryable = isinstance(code, int) and (code == 429 or code >= 500)
            raise LLMError(
                "rate_limited" if code == 429 else "provider_error", str(e), retryable=retryable
            ) from e
        yield StreamEvent(
            done=True, stop_reason=stop, usage=usage, model=req.model, sources=clean_sources(sources)
        )

    async def aclose(self):
        aio_close = getattr(self.client.aio, "aclose", None)
        if aio_close:
            await aio_close()

    async def complete(self, req: LLMRequest) -> str:
        return "".join([ev.delta async for ev in self.stream(req)])
