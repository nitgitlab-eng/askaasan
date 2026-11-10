from django.urls import path

from . import api

urlpatterns = [
    path("pair/start/", api.pair_start),
    path("pair/claim/", api.pair_claim),
    path("devices/", api.devices),
    path("devices/<int:pk>/", api.device_detail),
    path("disconnect/", api.disconnect),
    path("tasks/", api.tasks),
    path("tasks/<int:pk>/submit/", api.submit),
    path("authoring/activities/<int:pk>/steps/", api.activity_steps),
]
