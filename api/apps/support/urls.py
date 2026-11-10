from django.urls import path

from . import api

urlpatterns = [
    path("articles/", api.articles),
    path("articles/<slug:slug>/", api.article),
    path("ask/", api.ask),
    path("reports/", api.reports),
]

admin_urlpatterns = [
    path("reports/", api.admin_reports),
    path("reports/<int:pk>/", api.admin_report),
    path("help/", api.admin_articles),
    path("help/<int:pk>/", api.admin_article),
]
