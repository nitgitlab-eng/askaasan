from django.urls import path

from . import api

urlpatterns = [
    path("", api.calendar_status),
    path("replan/", api.replan_view),
    path("<str:provider>/connect/", api.connect),
    path("<str:provider>/callback/", api.callback),
    path("<str:provider>/", api.disconnect),
]

admin_urlpatterns = [
    path("calendar-apps/", api.admin_apps),
    path("calendar-apps/<str:provider>/", api.admin_app),
]
