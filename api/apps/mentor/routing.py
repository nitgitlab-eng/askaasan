from django.urls import path

from .consumers import AssistantConsumer

websocket_urlpatterns = [path("ws/assistant/", AssistantConsumer.as_asgi())]
