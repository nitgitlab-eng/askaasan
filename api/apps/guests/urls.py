from django.urls import path

from . import api, public

urlpatterns = [
    # Creator: guest links
    path("links/", api.links),
    path("links/<int:pk>/", api.link_detail),
    path("links/<int:pk>/qr/", api.link_qr),
    path("links/<int:pk>/stats/", api.link_stats),
    path("links/<int:pk>/export.csv", api.link_export),
    path("targets/", api.targets),
    path("claim/", api.claim_progress),
    # Org managers: guest campaigns
    path("orgs/<slug:slug>/campaigns/", api.org_campaigns),
    path("campaigns/<int:pk>/", api.campaign_detail),
    path("campaigns/<int:pk>/send-all/", api.campaign_send_all),
    path("prospects/<int:pk>/", api.prospect_detail),
    path("prospects/<int:pk>/regenerate/", api.prospect_regenerate),
    path("prospects/<int:pk>/send/", api.prospect_send),
    # Public guest pages (no login, throttled)
    path("unsubscribe/", public.unsubscribe),
    path("public/<slug:slug>/", public.landing),
    path("public/<slug:slug>/start/", public.start),
    path("public/<slug:slug>/resume/", public.resume),
    path("public/<slug:slug>/email-link/", public.email_link),
    path("public/<slug:slug>/lesson/<int:lesson_id>/", public.lesson),
    path("public/<slug:slug>/lesson/<int:lesson_id>/done/", public.lesson_done),
    path("public/<slug:slug>/attempt/<int:activity_id>/", public.attempt),
    path("public/<slug:slug>/finish/", public.finish),
    path("public/<slug:slug>/summary/", public.summary),
    path("public/<slug:slug>/role-play/", public.roleplay),
    path("public/<slug:slug>/role-play/say/", public.roleplay_say),
    path("public/<slug:slug>/role-play/end/", public.roleplay_end),
]
