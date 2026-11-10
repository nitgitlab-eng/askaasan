from django.urls import path

from apps.orgs import sso

from . import guardian, passkeys, push_api, views

urlpatterns = [
    path("register/", views.register),
    path("login/", views.login),
    path("refresh-token/", views.refresh),
    path("logout/", views.logout),
    path("google/", views.google_login),
    path("auth-config/", views.auth_config),
    path("sso/lookup/", sso.lookup),  # organisation SSO (apps/orgs/sso.py)
    path("sso/start/", sso.start),
    path("sso/callback/", sso.callback),
    path("me/", views.me),
    path("guardian/", guardian.my_guardian),
    path("unsubscribe/", views.unsubscribe_view),
    path("profile/", views.update_profile),
    path("preferences/", views.preferences),
    path("email-verification/request/", views.request_verification),
    path("email-verification/confirm/", views.confirm_verification),
    path("password-reset/request/", views.request_password_reset),
    path("password-reset/verify-otp/", views.verify_password_reset_otp),
    path("password-reset/confirm/", views.confirm_password_reset),
    path("passkeys/", passkeys.passkey_list),
    path("passkeys/<int:pk>/", passkeys.passkey_detail),
    path("passkey/register/begin/", passkeys.register_begin),
    path("passkey/register/complete/", passkeys.register_complete),
    path("passkey/authenticate/begin/", passkeys.authenticate_begin),
    path("passkey/authenticate/complete/", passkeys.authenticate_complete),
    path("reauth/", passkeys.reauth),
    path("push/", push_api.push_status),
    path("push/subscriptions/", push_api.push_subscriptions),
    path("push/test/", push_api.push_test),
    path("push/opened/", push_api.push_opened),
    path("push/reminders/resume/", push_api.push_resume),
]
