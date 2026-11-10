from django.urls import path

from . import admin_console, api

urlpatterns = [
    path("", api.my_certificates),
    path("<int:pk>/", api.certificate_detail),
    path("<int:pk>/revoke/", api.certificate_revoke),
    path("<int:pk>/pdf/", api.certificate_pdf),
    path("verify/<str:code>/", api.verify),
    path("share/", api.share),
    path("share/facts/", api.share_facts),
    path("orgs/<slug:slug>/", api.org_certificates),
    path("orgs/<slug:slug>/templates/", admin_console.org_templates),
    path("orgs/<slug:slug>/templates/preview/", admin_console.org_template_preview),
    path("orgs/<slug:slug>/templates/<int:pk>/", admin_console.org_template_detail),
    path("orgs/<slug:slug>/eligible/<int:member_id>/", api.org_eligible),
    path("orgs/<slug:slug>/<int:pk>/revoke/", api.org_revoke),
]
