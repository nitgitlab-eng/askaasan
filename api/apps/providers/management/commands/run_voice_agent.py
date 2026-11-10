"""Run Aasan's live voice agent (LiveKit): `run_voice_agent start` in production, `dev` locally,
`download-files` once at build time (the turn-detector and VAD models)."""

import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the LiveKit voice agent: start | dev | download-files."

    def add_arguments(self, parser):
        parser.add_argument("mode", nargs="?", default="start", choices=["start", "dev", "download-files"])

    def handle(self, *args, **opts):
        import os

        from django.conf import settings
        from livekit.agents import cli

        from apps.providers.voice.agent import server

        # The agents CLI reads the server and credentials from the environment and its own argv.
        for name in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
            if getattr(settings, name):
                os.environ.setdefault(name, getattr(settings, name))
        if opts["mode"] == "download-files":
            # Plugins register on import; only registered plugins get their model files downloaded.
            from livekit.plugins import sarvam, silero  # noqa: F401
            from livekit.plugins.turn_detector import multilingual  # noqa: F401
        sys.argv = [sys.argv[0], opts["mode"]]
        cli.run_app(server())
