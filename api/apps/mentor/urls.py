from django.urls import path

from . import feedback, views

urlpatterns = [
    path("conversations/", views.conversations),
    path("conversations/<int:pk>/", views.conversation_detail),
    path("feedback/<str:kind>/<int:pk>/", feedback.rate),
]
