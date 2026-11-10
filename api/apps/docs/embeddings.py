"""Optional semantic search: embeds note chunks with the admin-configured "embedding" provider.

If no provider/key is set, everything falls back to BM25 keyword search — nothing breaks."""

import logging
import math

from django.conf import settings

log = logging.getLogger(__name__)
MAX_BATCH = 96


def _cfg():
    from apps.providers.services import needs_key, resolve

    cfg = resolve("embedding")
    if settings.LLM_FORCE_PROVIDER == "fake":
        return cfg if cfg.enabled else None
    if not cfg.enabled or (needs_key(cfg.provider, "embedding") and not cfg.key):
        return None
    return cfg


def available() -> bool:
    try:
        return _cfg() is not None
    except Exception:  # noqa: BLE001
        return False


def embed(texts: list[str]) -> list[list[float]] | None:
    """Vectors for texts, or None if embeddings aren't configured / the call failed."""
    cfg = _cfg()
    if not cfg or not texts:
        return None
    try:
        if settings.LLM_FORCE_PROVIDER == "fake":  # deterministic toy vectors for tests
            return [_toy(t) for t in texts]
        out: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            batch = [t[:6000] for t in texts[i : i + MAX_BATCH]]
            if cfg.provider == "openai":
                import openai

                r = openai.OpenAI(api_key=cfg.key, timeout=60).embeddings.create(model=cfg.model, input=batch)
                out += [d.embedding for d in r.data]
            elif cfg.provider == "gemini":
                from google import genai

                r = genai.Client(api_key=cfg.key).models.embed_content(model=cfg.model, contents=batch)
                out += [e.values for e in r.embeddings]
            else:
                return None
        return out
    except Exception:
        log.warning("embedding call failed; using keyword search", exc_info=True)
        return None


def _toy(text: str) -> list[float]:
    from .search import tokens

    v = [0.0] * 64
    for tok in tokens(text):
        v[hash(tok) % 64] += 1.0
    return v


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
