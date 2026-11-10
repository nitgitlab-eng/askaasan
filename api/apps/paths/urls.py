from django.urls import path

from . import api, plan_api, profile_api

urlpatterns = [
    path("skills/", api.skills),
    path("skills/reorder/", api.skills_reorder),
    path("skills/bulk/", api.skills_bulk),
    path("skills/<slug:slug>/", api.skill_update),
    path("recommendations/", api.recommendations),
    path("curated/", api.curated),
    path("curated/<slug:slug>/", api.curated_detail),
    path("curated/<slug:slug>/join/", api.curated_join),
    path("curated/<slug:slug>/steps/<int:index>/", api.curated_link_step),
    path("careers/", api.careers),
    path("careers/<slug:slug>/", api.career_detail),
    path("careers/<slug:slug>/assessment/", api.career_assessment),
    path("careers/<slug:slug>/plan/", plan_api.career_plan),
    path("careers/<slug:slug>/plan/goals/<str:gid>/", plan_api.career_plan_goal),
    path("assessments/<int:pk>/submit/", api.career_assessment_submit),
    path("placement/", api.placement),
    path("placement/<int:pk>/submit/", api.placement_submit),
    path("onboarding-chat/", api.onboarding_chat),
    path("onboarding-apply/", api.onboarding_apply),
    path("company/", profile_api.company),
    path("role-summary/", profile_api.role_summary),
    path("cv/", profile_api.cv),
    path("target-role/", profile_api.target_role),
]
