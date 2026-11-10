"""Validate learner-supplied images (data URLs) before they reach a vision model."""

import base64

from .base import Image

MAGIC = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}


def decode_data_url(data_url, max_bytes: int = 600_000) -> Image | None:
    """Accept only real JPEG/PNG/WebP bytes, whatever the data URL claims."""
    if not isinstance(data_url, str) or not data_url.startswith("data:image/") or ";base64," not in data_url:
        return None
    b64 = data_url.split(";base64,", 1)[1]
    if len(b64) > max_bytes * 4 // 3 + 4:
        return None
    try:
        raw = base64.b64decode(b64, validate=True)
    except ValueError:
        return None
    for magic, mime in MAGIC.items():
        if raw.startswith(magic):
            return Image(mime, b64)
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return Image("image/webp", b64)
    return None
