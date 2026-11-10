"""BM25 keyword retrieval (no external embedding service needed). The tokenizer
keeps whole Tamil words: Python's \\w alone splits on Tamil vowel signs."""

import math
import re
from collections import Counter

TOKEN = re.compile(r"[\w஀-௿]+")
STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "is",
    "are",
    "for",
    "on",
    "with",
    "what",
    "how",
    "why",
    "it",
    "this",
    "that",
}


def tokens(text: str) -> list[str]:
    return [t for t in (m.casefold() for m in TOKEN.findall(text)) if t not in STOP and len(t) > 1]


def bm25(query: str, docs: list[str], k1: float = 1.4, b: float = 0.75) -> list[float]:
    q = tokens(query)
    toks = [tokens(d) for d in docs]
    n = len(docs) or 1
    avg = sum(len(t) for t in toks) / n or 1
    df = Counter(w for t in toks for w in set(t))
    scores = []
    for t in toks:
        tf = Counter(t)
        s = 0.0
        for w in q:
            if w not in tf:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            s += idf * tf[w] * (k1 + 1) / (tf[w] + k1 * (1 - b + b * len(t) / avg))
        scores.append(s)
    return scores


def top_chunks(document, query: str, k: int = 6):
    """BM25 keywords; when chunks have embeddings, fused with semantic similarity (reciprocal-rank fusion)."""
    chunks = list(document.chunks.all())
    if not chunks:
        return []
    scores = bm25(query, [c.text for c in chunks])
    by_kw = sorted(range(len(chunks)), key=lambda i: -scores[i])
    if all(c.embedding for c in chunks):
        from .embeddings import cosine, embed

        qv = embed([query])
        if qv:
            sims = [cosine(qv[0], c.embedding) for c in chunks]
            by_sem = sorted(range(len(chunks)), key=lambda i: -sims[i])
            rrf = [0.0] * len(chunks)
            for rank, i in enumerate(by_kw):
                rrf[i] += 1 / (60 + rank) if scores[i] > 0 else 0
            for rank, i in enumerate(by_sem):
                rrf[i] += 1 / (60 + rank)
            return [chunks[i] for i in sorted(range(len(chunks)), key=lambda i: -rrf[i])[:k]]
    hits = [chunks[i] for i in by_kw[:k] if scores[i] > 0]
    return hits or chunks[: min(k, 3)]  # vague question → start of the document


_SENT = re.compile(r"(?<=[.!?।])\s+|\n+")


def best_snippet(text: str, query: str, max_len: int = 260) -> str:
    """The sentence (plus its neighbour) in a chunk that best matches `query`."""
    sents = [s.strip() for s in _SENT.split(text) if s.strip()]
    if not sents:
        return text[:max_len]
    q = set(tokens(query))
    scores = [len(q & set(tokens(s))) for s in sents]
    i = max(range(len(sents)), key=lambda k: scores[k])
    snippet = sents[i]
    if i + 1 < len(sents) and len(snippet) + len(sents[i + 1]) < max_len:
        snippet += " " + sents[i + 1]
    return snippet[:max_len]
