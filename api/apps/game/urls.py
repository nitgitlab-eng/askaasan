from django.urls import path

from . import api

urlpatterns = [
    path("status/", api.game_status),
    path("achievements/", api.achievements),
    path("shop/", api.shop),
    path("shop/buy/", api.buy),
    path("streak/repair/", api.streak_repair),
    path("leaderboard/", api.leaderboard),
    path("settings/", api.settings_view),
    path("boss/<int:section_id>/result/", api.boss_result),
    path("notifications/", api.notifications),
    path("notifications/read/", api.notifications_read),
    path("nudges/", api.nudges_view),
    path("plan/", api.week_plan),
    path("plan.ics", api.study_plan_ics),
    path("calendar-feed/", api.calendar_feed),
    path("calendar/<str:token>.ics", api.calendar_feed_ics),
]
