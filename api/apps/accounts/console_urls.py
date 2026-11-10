"""Admin console routes added with staff roles (mounted under /api/admin/ in config/urls.py)."""

from django.urls import path

from apps.credentials import admin_console as certs
from apps.orgs import admin_console as orgs

from . import admin_console as v

admin_urlpatterns = [
    path("staff/", v.staff),
    path("audit/", v.audit),
    path("users/", v.users),
    path("users/<int:pk>/", v.user_detail),
    path("users/<int:pk>/action/", v.user_action),
    path("orgs/", orgs.orgs),
    path("orgs/<int:pk>/", orgs.org_detail),
    path("certificates/", certs.certificates),
    path("certificates/<int:pk>/revoke/", certs.certificate_revoke),
    path("certificates/<int:pk>/refresh-name/", certs.certificate_refresh_name),
    path("certificate-templates/", certs.templates),
    path("certificate-templates/preview/", certs.template_preview),
    path("certificate-templates/<int:pk>/", certs.template_detail),
]
