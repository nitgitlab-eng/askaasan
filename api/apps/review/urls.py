from django.urls import path

from . import api

urlpatterns = [
    path("overview/", api.overview),
    path("session/", api.session),
    path("cards/<int:pk>/answer/", api.answer),
    path("mastery/<int:curriculum_id>/", api.mastery_graph),
]
