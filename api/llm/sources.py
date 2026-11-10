"""Web sources from a search-grounded reply, as the app shows them: [{"title", "url"}], http(s) only, deduped."""

MAX_SOURCES = 6


def clean_sources(sources, limit: int = MAX_SOURCES) -> list[dict]:
    seen, out = set(), []
    for s in sources or []:
        url = (s.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or len(url) > 500 or url in seen:
            continue
        if any(c in url for c in " \n\r\t\"'<>"):
            continue
        seen.add(url)
        title = " ".join(str(s.get("title") or "").split())[:200] or url
        out.append({"title": title, "url": url})
        if len(out) >= limit:
            break
    return out
