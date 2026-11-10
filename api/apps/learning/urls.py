from django.urls import path

from . import api, own_api, tutor, widget

urlpatterns = [
    path("curriculums/", api.curriculums),
    path("curriculums/<int:pk>/", api.curriculum_detail),
    path("curriculums/<int:pk>/retry/", api.curriculum_retry),
    path("curriculums/<int:pk>/reset/", api.curriculum_reset),
    path("curriculums/<int:pk>/edit/", own_api.edit_state),
    path("curriculums/<int:pk>/edit/add-section/", own_api.add_section),
    path("curriculums/<int:pk>/edit/hidden/", own_api.toggle_hidden),
    path("curriculums/<int:pk>/edit/sources/", own_api.sources),
    path("curriculums/<int:pk>/edit/reorder/", own_api.reorder_lessons),
    path("curriculums/<int:pk>/edit/<str:direction>/", own_api.undo_redo),
    path("subsections/<int:pk>/", api.subsection_detail),
    path("subsections/<int:pk>/start/", api.subsection_start),
    path("subsections/<int:pk>/complete/", api.subsection_complete),
    path("subsections/<int:pk>/practice/", api.subsection_practice),
    path("activities/<int:pk>/attempt/", api.activity_attempt),
    path("activities/<int:pk>/roleplay/", api.activity_roleplay),
    path("subsections/<int:pk>/feedback/", api.subsection_feedback),
    path("subsections/<int:pk>/widget/", widget.widget),
    path("subsections/<int:pk>/widget/check/", widget.widget_check),
    path("widgets/<int:pk>/frame/", widget.widget_frame),
    path("subsections/<int:pk>/tutor/", tutor.tutor),
    path("subsections/<int:pk>/tutor/reply/", tutor.tutor_reply),
    path("match-choice/", api.match_choice),
    path("continue/", api.continue_learning),
]
