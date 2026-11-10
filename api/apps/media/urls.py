from django.urls import path

from . import api

urlpatterns = [
    path("upload/", api.upload),
    path("generate/", api.generate_image),
    path("mine/", api.mine),
    path("lectures/<int:uid>/<str:name>", api.serve_lecture),
    path("speech/<str:name>", api.serve_speech),
    path("<str:name>", api.serve),
]
