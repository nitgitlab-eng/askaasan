from django.urls import path

from . import api, v1

# /api/orgs/<slug>/integrations/… (cockpit, JWT, org admins)
org_urlpatterns = [
    path("keys/", api.keys),
    path("keys/<int:pk>/", api.key_detail),
    path("webhooks/", api.webhooks),
    path("webhooks/<int:pk>/", api.webhook_detail),
    path("webhooks/<int:pk>/rotate-secret/", api.webhook_rotate),
    path("webhooks/<int:pk>/test/", api.webhook_test),
    path("webhooks/<int:pk>/deliveries/", api.webhook_deliveries),
    path("webhooks/<int:pk>/deliveries/<int:did>/redeliver/", api.webhook_redeliver),
]

# /api/v1/orgs/<slug>/… (API keys only)
v1_urlpatterns = [
    path("members/", v1.members),
    path("members/<int:pk>/", v1.member_detail),
    path("assignments/", v1.assignments),
    path("assignments/<int:pk>/progress/", v1.assignment_progress),
    path("certificates/", v1.certificates),
    path("training-records/", v1.training_records),
]
