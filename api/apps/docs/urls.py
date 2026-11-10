from django.urls import path

from . import api

urlpatterns = [
    path("", api.documents),
    path("<int:pk>/", api.document_detail),
]
