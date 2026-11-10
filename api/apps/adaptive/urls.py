from django.urls import path

from . import api

urlpatterns = [
    path("goals/", api.goals),
    path("goals/<int:pk>/", api.goal_detail),
    path("goals/<int:pk>/choose/", api.goal_choose),
    path("goals/<int:pk>/constraints/", api.goal_constraints),
    path("courses/<int:pk>/path/", api.course_path),
    path("courses/<int:pk>/skill-map/", api.course_skill_map),
]
