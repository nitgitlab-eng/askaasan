"""Provider-neutral types for the LLM layer."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal, Protocol

Role = Literal["user", "assistant"]


@dataclass
class Image:
    media_type: str  # image/jpeg | image/png | image/webp
    data_b64: str


@dataclass
class ChatMessage:
    role: Role
    content: str
    # Only user turns carry images (Live Class camera/screen snapshots). Never persisted.
    images: list[Image] = field(default_factory=list)


@dataclass
class LLMRequest:
    model: str
    system: str
    messages: list[ChatMessage]
    max_tokens: int = 8000
    # Abstract effort knob mapped by each adapter: "low" | "medium" | "high".
    effort: str = "low"
    # Strict JSON Schema for structured output (see llm/structured.py).
    json_schema: dict | None = None
    # Let the model search the web this turn (provider's own search tool); results come back as StreamEvent.sources.
    web_search: bool = False


@dataclass
class StreamEvent:
    """`delta` carries text; `status` says what the model is doing without text ("searching");
    the final event has done=True plus metadata and any web `sources` ([{"title", "url"}])."""

    delta: str = ""
    done: bool = False
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)
    model: str | None = None
    status: str | None = None
    sources: list = field(default_factory=list)


class LLMError(Exception):
    def __init__(self, code: str, message: str = "", retryable: bool = False):
        super().__init__(message or code)
        self.code = code
        self.retryable = retryable


class Provider(Protocol):
    name: str

    def stream(self, req: LLMRequest) -> AsyncIterator[StreamEvent]: ...

    async def complete(self, req: LLMRequest) -> str: ...

    async def aclose(self) -> None: ...
