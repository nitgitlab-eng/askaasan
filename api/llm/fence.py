"""Prompt fences for untrusted text (learner answers, documents, staff-written setup).

Untrusted text placed between <tag> … </tag> delimiters must not be able to close the fence early (and then write
"instructions" outside it) or open a look-alike fence. defang() swaps the '<' of any opening or closing tag with
one of the given names for '‹', which the model still reads but which no longer matches the delimiter.
"""

import re


def defang(text: str, *tags: str) -> str:
    """Neutralise `<tag` / `</tag` (any case, optional spaces) for each name in `tags`."""
    if not text or not tags:
        return text or ""
    names = "|".join(re.escape(t) for t in tags)
    return re.sub(rf"<\s*/?\s*({names})\b", lambda m: m.group(0).replace("<", "‹"), text, flags=re.IGNORECASE)


def fence(tag: str, text: str) -> str:
    """`<tag>\\ntext\\n</tag>` with `text` unable to break out of the fence."""
    return f"<{tag}>\n{defang(text, tag)}\n</{tag}>"
