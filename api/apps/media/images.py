"""Image pipeline: verify → strip metadata → resize → WebP, plus AI generation adapters."""

import base64
import io
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000  # refuse decompression bombs before decoding
MAX_SIDE = 1600
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


class ImageError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def process(raw: bytes) -> tuple[bytes, int, int]:
    """Any JPEG/PNG/WebP/GIF → clean WebP. Re-encoding drops EXIF (incl. phone GPS) and any embedded payloads."""
    if len(raw) > MAX_UPLOAD:
        raise ImageError("too_large")
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise ImageError("bad_type")
        if probe.width * probe.height > MAX_PIXELS:
            raise ImageError("too_large")
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)  # keep phone photos upright before metadata is dropped
        img.seek(0)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ImageError("bad_image") from e
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "WEBP", quality=85, method=4)
    return out.getvalue(), img.width, img.height


def store(owner, data: bytes, width: int, height: int, *, kind: str, prompt: str = "", alt: str = ""):
    from .models import MediaAsset

    name = f"{uuid.uuid4().hex}.webp"
    default_storage.save(f"aasan/{name}", ContentFile(data))
    return MediaAsset.objects.create(
        owner=owner,
        name=name,
        kind=kind,
        prompt=prompt[:500],
        alt=alt[:200],
        width=width,
        height=height,
        size=len(data),
    )


STYLE = (
    "Style: friendly flat educational illustration for Indian school and college students, clean shapes, bright "
    "but soft colours, plain background. Do NOT include any text, letters, numbers or labels. No real people, "
    "celebrities, brand logos or violence."
)


def generate(cfg, prompt: str) -> bytes:
    """Ask the admin-configured image provider for one illustration. Returns raw image bytes."""
    full = f"{prompt.strip()[:400]}\n\n{STYLE}"
    if settings.LLM_FORCE_PROVIDER == "fake" or cfg.provider == "fake":
        buf = io.BytesIO()
        Image.new("RGB", (512, 512), (249, 115, 22)).save(buf, "PNG")
        return buf.getvalue()
    try:
        if cfg.provider == "openai":
            import openai

            r = openai.OpenAI(api_key=cfg.key, timeout=120).images.generate(
                model=cfg.model, prompt=full, size="1024x1024", n=1
            )
            return base64.b64decode(r.data[0].b64_json)
        if cfg.provider == "gemini":
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=cfg.key)
            if cfg.model.startswith("imagen"):
                r = client.models.generate_images(
                    model=cfg.model, prompt=full, config=types.GenerateImagesConfig(number_of_images=1)
                )
                return r.generated_images[0].image.image_bytes
            r = client.models.generate_content(model=cfg.model, contents=full)
            for part in r.candidates[0].content.parts:
                if part.inline_data and part.inline_data.data:
                    return part.inline_data.data
            raise ImageError("no_image", "The model returned no image (it may have declined the prompt).")
    except ImageError:
        raise
    except Exception as e:  # provider SDKs raise many types; surface a clean code
        msg = str(e)
        code = "content_policy" if "safety" in msg.lower() or "policy" in msg.lower() else "provider_error"
        raise ImageError(code, msg[:300]) from e
    raise ImageError("unknown_provider", cfg.provider)
