"""Validate the configured AI providers (admin console first, then .env)
with one tiny real request per capability. Prints status only, never keys."""

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.providers.services import needs_key, resolve
from llm.base import ChatMessage, LLMError, LLMRequest
from llm.router import complete_once, provider_for

PROBE = "Reply with exactly: சரி"


class Command(BaseCommand):
    help = "Check that each LLM capability has a key and answers a 1-line probe."

    def add_arguments(self, parser):
        parser.add_argument("--no-call", action="store_true", help="Only check keys are present.")

    def handle(self, *args, **opts):
        if settings.LLM_FORCE_PROVIDER:
            self.stdout.write(
                self.style.WARNING(
                    f"LLM_FORCE_PROVIDER={settings.LLM_FORCE_PROVIDER} is set: the app uses demo replies until you blank it. "
                    "Testing the real providers anyway."
                )
            )
        ok = True
        for cap in ("tutor", "utility", "stt", "tts", "tts_ta"):
            cfg = resolve(cap)
            label = f"{cap:<8} {cfg.provider}:{cfg.model or '-':<28} (from {cfg.source})"
            if not needs_key(cfg.provider, cap):
                self.stdout.write(self.style.SUCCESS(f"✓ {label} runs in the browser, no key"))
                continue
            if not cfg.key:
                ok = False
                self.stdout.write(self.style.ERROR(f"✗ {label} missing key"))
                continue
            if opts["no_call"] or cap in ("stt", "tts", "tts_ta"):
                hint = (
                    " (test playback/recording from the admin console)"
                    if cap in ("stt", "tts", "tts_ta")
                    else ""
                )
                self.stdout.write(self.style.SUCCESS(f"✓ {label} key present{hint}"))
                continue
            try:
                reply = asyncio.run(
                    complete_once(
                        provider_for(cfg),
                        LLMRequest(
                            model=cfg.model,
                            system="You are a test probe.",
                            messages=[ChatMessage("user", PROBE)],
                            max_tokens=200,
                        ),
                    )
                )
                self.stdout.write(self.style.SUCCESS(f"✓ {label} replied: {reply.strip()[:40]!r}"))
            except LLMError as e:
                ok = False
                self.stdout.write(self.style.ERROR(f"✗ {label} {e.code}: {str(e)[:160]}"))
        self.stdout.write(
            self.style.SUCCESS("All OK") if ok else self.style.ERROR("Some capabilities need attention")
        )
