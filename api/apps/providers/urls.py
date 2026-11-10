from django.urls import path

from . import admin_api, features, overview, voice_api

admin_urlpatterns = [
    path("features/", features.admin_features),
    path("overview/", overview.overview),
    path("model-prices/", overview.model_prices),
    path("system-check/", overview.system_check),
    path("providers/", admin_api.list_providers),
    path("providers/<str:capability>/", admin_api.update_provider),
    path("providers/<str:capability>/test/", admin_api.test_provider),
]

voice_urlpatterns = [
    path("config/", voice_api.voice_config),
    path("transcribe/", voice_api.transcribe_view),
    path("speak/", voice_api.speak_view),
    path("clip/", voice_api.clip_view),
    path("live/token/", voice_api.live_token_view),
]
