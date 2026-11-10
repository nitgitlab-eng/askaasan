"""Append any missing variables from .env.example to .env as placeholders.

Never prints values and never changes lines that already exist, so it is safe
to run after you've pasted real keys."""

import re
import secrets
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

NAME = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=")


def vapid_keys() -> dict:
    """A fresh web-push (VAPID) key pair as base64url: the raw 32-byte private key and the uncompressed public point.
    Blank when the crypto libraries are missing (push then stays off until keys are pasted in)."""
    try:
        from cryptography.hazmat.primitives import serialization
        from py_vapid import Vapid
        from py_vapid.utils import b64urlencode

        v = Vapid()
        v.generate_keys()
        private = b64urlencode(v.private_key.private_numbers().private_value.to_bytes(32, "big"))
        public = b64urlencode(
            v.public_key.public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )
    except Exception:  # noqa: BLE001 — no crypto libraries: leave the keys blank
        private = public = ""
    return {"WEBPUSH_VAPID_PUBLIC_KEY": public, "WEBPUSH_VAPID_PRIVATE_KEY": private}


class Command(BaseCommand):
    help = "Add missing placeholder keys from .env.example to .env (no values printed)."

    def handle(self, *args, **opts):
        base = Path(settings.BASE_DIR)
        example, env = base / ".env.example", base / ".env"
        existing = env.read_text() if env.exists() else ""
        have = {m.group(1) for line in existing.splitlines() if (m := NAME.match(line))}

        added = []
        lines = []
        # A VAPID pair is generated only when neither half exists yet (a lone half would never match).
        vapid = (
            vapid_keys()
            if not {"WEBPUSH_VAPID_PUBLIC_KEY", "WEBPUSH_VAPID_PRIVATE_KEY"} & have
            else {"WEBPUSH_VAPID_PUBLIC_KEY": "", "WEBPUSH_VAPID_PRIVATE_KEY": ""}
        )
        for line in example.read_text().splitlines():
            m = NAME.match(line)
            if not m or line.lstrip().startswith("#") or m.group(1) in have:
                continue
            key = m.group(1)
            # Generate a real secret key instead of leaving it blank.
            if key in ("DJANGO_SECRET_KEY", "AASAN_SECRETS_KEY"):
                lines.append(f"{key}={secrets.token_urlsafe(50)}")
            elif key in vapid:
                lines.append(f"{key}={vapid[key]}")
            else:
                lines.append(line)
            added.append(key)

        if added:
            with env.open("a") as fh:
                if existing and not existing.endswith("\n"):
                    fh.write("\n")
                fh.write("\n# --- added by setup_env ---\n" + "\n".join(lines) + "\n")
        env.chmod(0o600)
        self.stdout.write(f"Added {len(added)} placeholder(s): {', '.join(added) or 'none'}")
        self.stdout.write(f"Already present (untouched): {', '.join(sorted(have)) or 'none'}")
