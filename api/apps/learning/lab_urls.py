from django.urls import path

from . import lab_api as v

urlpatterns = [
    path("courses/", v.lab_courses),
    path("courses/<int:pk>/", v.lab_course),
    path("courses/<int:pk>/sections/", v.lab_add_section),
    path("courses/<int:pk>/reorder/", v.lab_reorder),
    path("courses/<int:pk>/publish/", v.lab_publish),
    path("courses/<int:pk>/share/rotate/", v.lab_rotate_share),
    path("sections/<int:pk>/", v.lab_section),
    path("sections/<int:pk>/subsections/", v.lab_add_subsection),
    path("subsections/<int:pk>/", v.lab_subsection),
    path("subsections/<int:pk>/generate/", v.lab_generate_lesson),
    path("subsections/<int:pk>/video-questions/", v.lab_video_questions),
    path("subsections/<int:pk>/activities/", v.lab_add_activity),
    path("activities/<int:pk>/", v.lab_activity),
]

catalog_urlpatterns = [path("", v.catalog)]

share_urlpatterns = [
    path("<str:token>/", v.share_info),
    path("<str:token>/enroll/", v.share_enroll),
    path("<str:token>/lesson/", v.guest_lesson),
    path("<str:token>/attempt/<int:activity_id>/", v.guest_attempt),
]

admin_urlpatterns = [
    path("catalog/", v.moderation_queue),
    path("catalog/<int:pk>/", v.moderate),
    path("creators/", v.set_creator),
]
