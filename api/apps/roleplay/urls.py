from django.urls import path

from . import api

urlpatterns = [
    path("scenarios/", api.scenarios),
    path("scenarios/generate/", api.generate),
    path("scenarios/<int:pk>/", api.scenario_detail),
    path("sessions/", api.sessions),
    path("sessions/<int:pk>/", api.session_detail),
    path("sessions/<int:pk>/end/", api.session_end),
    path("sessions/<int:pk>/coach/", api.session_coach),
    path("sessions/<int:pk>/hint/", api.session_hint),
]
