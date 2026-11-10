import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.urls import path

from apps.live.consumers import LiveConsumer
from apps.mentor.routing import websocket_urlpatterns
from apps.providers.voice.stream import VoiceStreamConsumer
from apps.roleplay.consumers import RolePlayConsumer
from apps.workshops.consumers import MonitorConsumer, WorkshopConsumer
from config.asgi_threads import PerConnectionThreads

application = ProtocolTypeRouter(
    {
        "http": django_asgi,
        "websocket": PerConnectionThreads(
            AllowedHostsOriginValidator(
                URLRouter(
                    [
                        *websocket_urlpatterns,
                        path("ws/roleplay/", RolePlayConsumer.as_asgi()),
                        path("ws/live/", LiveConsumer.as_asgi()),
                        path("ws/voice-stream/", VoiceStreamConsumer.as_asgi()),
                        path("ws/workshop/<int:session_id>/", WorkshopConsumer.as_asgi()),
                        path("ws/workshop-runs/<int:run_id>/monitor/", MonitorConsumer.as_asgi()),
                    ]
                )
            )
        ),
    }
)
