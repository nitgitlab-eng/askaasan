from django.urls import path

from . import api, mcp, oauth

# Mounted at api/connect/
urlpatterns = [
    path("me/", api.me),
    path("authorize/", oauth.consent),
    path("oauth/register", oauth.register),
    path("oauth/token", oauth.token),
    path("oauth/revoke", oauth.revoke),
    path("orgs/<slug:slug>/clients/", api.clients),
    path("orgs/<slug:slug>/clients/<int:pk>/", api.client_detail),
    path("orgs/<slug:slug>/audit/", api.audit),
]

# Mounted at the site root. The web proxy must forward /.well-known/oauth-authorization-server and
# /.well-known/oauth-protected-resource(/api/mcp) to Django (clients look for them at the origin).
root_urlpatterns = [
    path("api/mcp", mcp.endpoint),
    path("api/mcp/", mcp.endpoint),
    path("api/.well-known/oauth-authorization-server", oauth.authorization_server_metadata),
    path("api/.well-known/oauth-protected-resource", oauth.protected_resource_metadata),
    path(".well-known/oauth-authorization-server", oauth.authorization_server_metadata),
    path(".well-known/oauth-protected-resource", oauth.protected_resource_metadata),
    path(".well-known/oauth-protected-resource/api/mcp", oauth.protected_resource_metadata),
]
