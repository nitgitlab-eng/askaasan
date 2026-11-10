from django.urls import path

from . import admin_api, api, extras, family_api, refunds, subscriptions

urlpatterns = [
    path("", api.overview),
    path("quote/", api.quote_view),
    path("checkout/", api.checkout),
    path("verify/", api.verify),
    path("failed/", api.failed),
    path("history/", api.history),
    path("webhook/", api.webhook),
    path("subscribe/", subscriptions.subscribe),
    path("subscription/", subscriptions.subscription),
    path("subscription/verify/", subscriptions.subscription_verify),
    path("subscription/cancel/", subscriptions.subscription_cancel),
    path("subscription/resume/", subscriptions.subscription_resume),
    path("redeem/", extras.redeem),
    path("family/", family_api.family),
    path("family/invite/", family_api.invite),
    path("family/invites/<int:pk>/", family_api.invite_detail),
    path("family/invites/<str:token>/", family_api.invite_preview),
    path("family/accept/", family_api.accept),
    path("family/members/<int:pk>/remove/", family_api.remove_member),
    path("family/leave/", family_api.leave),
    path("invoices/<str:number>.pdf", extras.invoice_pdf),
    path("orgs/<slug:slug>/", extras.org_billing),
    path("orgs/<slug:slug>/assign-seats/", extras.org_assign_seats),
    path("orgs/<slug:slug>/redeem-codes/", extras.org_redeem_codes),
]

admin_urlpatterns = [
    path("payments/config/", admin_api.config),
    path("payments/test/", admin_api.test_keys),
    path("payments/orders/", admin_api.orders),
    path("payments/grant/", admin_api.grant),
    path("payments/subscriptions/", subscriptions.admin_subscriptions),
    path("plans/", admin_api.plans),
    path("plans/<int:pk>/", admin_api.plan_detail),
    path("promos/", extras.admin_promos),
    path("promos/<int:pk>/", extras.admin_promo),
    path("redeem-codes/", extras.admin_redeem_codes),
    path("invoices/", extras.admin_invoices),
    path("refunds/", refunds.refunds),
    path("family-groups/", family_api.admin_family_groups),
    path("gifts/", family_api.admin_gifts),
]
