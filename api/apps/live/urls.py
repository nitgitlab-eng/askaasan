from django.urls import path

from . import api

urlpatterns = [
    path("sessions/", api.sessions),
    path("sessions/<int:pk>/", api.session_detail),
]
