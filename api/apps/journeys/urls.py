from django.urls import path

from . import api

urlpatterns = [
    path("me/", api.my_journeys),
    path("me/<int:aid>/", api.my_journey),
    path("me/<int:aid>/items/<int:iid>/", api.my_tick),
    path("orgs/<slug:slug>/", api.journeys),
    path("orgs/<slug:slug>/options/", api.options),
    path("orgs/<slug:slug>/people/", api.people),
    path("orgs/<slug:slug>/ai-draft/", api.ai_draft),
    path("orgs/<slug:slug>/<int:pk>/", api.journey_detail),
    path("orgs/<slug:slug>/<int:pk>/duplicate/", api.journey_duplicate),
    path("orgs/<slug:slug>/<int:pk>/items/", api.items),
    path("orgs/<slug:slug>/<int:pk>/items/<int:iid>/", api.item_detail),
    path("orgs/<slug:slug>/<int:pk>/assign/", api.assign),
    path("orgs/<slug:slug>/<int:pk>/assignees/<int:aid>/", api.assignee),
    path("orgs/<slug:slug>/<int:pk>/progress/", api.progress),
    path("orgs/<slug:slug>/<int:pk>/progress.csv", api.progress_csv),
]
