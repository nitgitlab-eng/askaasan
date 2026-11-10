"""Ask an LLM for JSON that validates against a Pydantic model.

Claude/OpenAI get a strict JSON Schema (constrained decoding); others get the
schema in the prompt. Every result is validated with Pydantic and retried once
with the validation error, so callers always receive a typed object or an
LLMError."""

import asyncio
import json
import re
from copy import deepcopy

from pydantic import BaseModel, ValidationError

from .base import ChatMessage, LLMError, LLMRequest, Provider
from .router import aclose, resolve

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema → strict JSON Schema: refs inlined, every object closed
    with all properties required, and keywords unsupported by constrained
    decoding (titles, defaults, numeric/length bounds) removed."""
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    drop = {
        "title",
        "default",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "discriminator",
        "examples",
    }

    def walk(node):
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(deepcopy(defs[node["$ref"].split("/")[-1]]))
        out = {}
        for k, v in node.items():
            if k == "properties":
                # Keys here are field NAMES (e.g. a field called "title"), not keywords.
                out[k] = {name: walk(sub) for name, sub in v.items()}
            elif k not in drop:
                out[k] = walk(v)
        if "oneOf" in out:
            out["anyOf"] = out.pop("oneOf")
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        if "const" in out and "type" not in out:
            out["type"] = "string"
        return out

    return walk(raw)


def _extract_json(text: str) -> str:
    text = _FENCE.sub("", text.strip())
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


async def complete_json[T: BaseModel](
    provider: Provider,
    model: str,
    system: str,
    user: str,
    model_cls: type[T],
    *,
    max_tokens: int = 8000,
    effort: str = "low",
    images: list | None = None,
) -> T:
    schema = strict_schema(model_cls)
    use_native = provider.name in ("anthropic", "openai")
    sys = (
        system
        if use_native
        else f"{system}\n\nReturn ONLY a JSON object matching this JSON Schema:\n{json.dumps(schema)}"
    )
    messages = [ChatMessage("user", user, images=list(images or []))]
    last_error = ""
    for _attempt in range(2):
        req = LLMRequest(
            model=model,
            system=sys,
            messages=messages,
            max_tokens=max_tokens,
            effort=effort,
            json_schema=schema if use_native else None,
        )
        text = await provider.complete(req)
        try:
            return model_cls.model_validate_json(_extract_json(text))
        except ValidationError as e:
            last_error = str(e)[:1500]
            messages = messages + [
                ChatMessage("assistant", text[:6000]),
                ChatMessage("user", f"That JSON was invalid:\n{last_error}\nReturn the corrected JSON only."),
            ]
    raise LLMError("invalid_structured_output", last_error)


def complete_json_sync[T: BaseModel](task: str, system: str, user: str, model_cls: type[T], **kw) -> T:
    """For sync callers (jobs, views). resolve() reads admin provider config
    from the DB, so it runs here in the caller's thread — never on the loop."""
    provider, model = resolve(task)

    async def run():
        try:
            return await complete_json(provider, model, system, user, model_cls, **kw)
        finally:
            await aclose(provider)  # release connections on THIS loop before it closes

    from .dbconn import release_db
    from .usage import flush_usage

    try:
        release_db()  # don't hold a pooled DB connection while the model thinks
        return asyncio.run(run())
    finally:
        flush_usage(provider)  # back on the caller's Django thread
