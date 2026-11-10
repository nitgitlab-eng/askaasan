"""'Research this topic' for the Creator Lab: one web-grounded call through the configured author model.

Each vendor exposes web search differently (Anthropic server tool, OpenAI Responses web_search, Gemini Google
Search grounding); this returns the same shape for all: {"notes": str, "sources": [{"title", "url"}]}."""

import asyncio

from .base import LLMError
from .sources import clean_sources

SYSTEM = """You research a topic for a teacher who is writing a course for Indian learners.
Search the web, then write concise research notes (max ~600 words): key facts, current numbers/dates,
India-relevant examples, common misconceptions, and anything that changed recently.
Use short bullet points. Mention which source each important fact came from. Do not write the course itself."""


async def _anthropic(p, model, prompt):
    client = p.inner.client
    last = None
    for tool in (
        "web_search_20260209",
        "web_search_20250305",
    ):  # newest first; older models only know the basic tool
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=4000,
                system=SYSTEM,
                messages=[{"role": "user", "content": prompt}],
                tools=[{"type": tool, "name": "web_search", "max_uses": 8}],
            )
            break
        except Exception as e:  # noqa: BLE001 — try the older tool version once, then give up
            last = e
    else:
        raise LLMError("web_search_unavailable", str(last))
    text, sources = [], []
    for block in resp.content:
        if block.type == "text":
            text.append(block.text)
            for c in getattr(block, "citations", None) or []:
                sources.append({"title": getattr(c, "title", ""), "url": getattr(c, "url", "")})
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            sources += [{"title": r.title, "url": r.url} for r in block.content if getattr(r, "url", None)]
    p.events.append(
        {"model": resp.model, "in": resp.usage.input_tokens, "out": resp.usage.output_tokens, "cached": 0}
    )
    return "".join(text), sources


async def _openai(p, model, prompt):
    resp = await p.inner.client.responses.create(
        model=model, instructions=SYSTEM, input=prompt, tools=[{"type": "web_search"}]
    )
    sources = []
    for item in resp.output or []:
        for c in getattr(item, "content", None) or []:
            for a in getattr(c, "annotations", None) or []:
                if getattr(a, "type", "") == "url_citation":
                    sources.append({"title": getattr(a, "title", ""), "url": a.url})
    u = resp.usage
    p.events.append(
        {
            "model": model,
            "in": getattr(u, "input_tokens", 0),
            "out": getattr(u, "output_tokens", 0),
            "cached": 0,
        }
    )
    return resp.output_text or "", sources


async def _gemini(p, model, prompt):
    from google.genai import types

    resp = await p.inner.client.aio.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM, tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
    )
    sources = []
    gm = resp.candidates[0].grounding_metadata if resp.candidates else None
    for ch in getattr(gm, "grounding_chunks", None) or []:
        if getattr(ch, "web", None):
            sources.append({"title": ch.web.title, "url": ch.web.uri})
    um = resp.usage_metadata
    p.events.append(
        {
            "model": model,
            "in": getattr(um, "prompt_token_count", 0) or 0,
            "out": getattr(um, "candidates_token_count", 0) or 0,
            "cached": 0,
        }
    )
    return resp.text or "", sources


def research(topic: str, context: str = "") -> dict:
    from .router import aclose, resolve
    from .usage import flush_usage

    provider, model = resolve("author")
    prompt = f"Topic: {topic}\n{('Course context: ' + context) if context else ''}"
    if provider.name == "fake":
        provider.events.append({"model": "fake", "in": 0, "out": 0, "cached": 0})
        flush_usage(provider)
        return {
            "notes": f"- Key facts about {topic} (demo research).\n- India example: UPI handles billions of payments a month.",
            "sources": [{"title": "Example source", "url": "https://example.org/research"}],
        }
    impl = {"anthropic": _anthropic, "openai": _openai, "gemini": _gemini}.get(provider.name)
    if not impl:
        raise LLMError("web_search_unsupported", provider.name)

    async def run():
        try:
            return await impl(provider, model, prompt)
        finally:
            await aclose(provider)

    try:
        from llm.dbconn import release_db

        release_db()
        text, sources = asyncio.run(run())
    except LLMError:
        raise
    except Exception as e:
        raise LLMError("web_search_failed", str(e)[:300]) from e
    finally:
        flush_usage(provider)
    if not text.strip():
        raise LLMError("web_search_failed", "empty")
    return {"notes": text.strip()[:12000], "sources": clean_sources(sources, limit=12)}
