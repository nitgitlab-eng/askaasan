from django.urls import path

from . import api

urlpatterns = [
    path("site/", api.site_info),
    path("subprocessors/", api.subprocessors),
    path("consent/", api.consent),
    path("export/", api.export),
    path("delete-account/", api.delete_account),
]
admin_urlpatterns = [
    path("site/", api.admin_site),
    path("mail/", api.admin_mail),
    path("mail/test/", api.admin_mail_test),
]
