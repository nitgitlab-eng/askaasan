from django.urls import path

from . import admin_api, api, mcp_server, org

urlpatterns = [
    path("runs/", api.runs),
    path("runs/<int:pk>/", api.run_detail),
    path("runs/<int:pk>/enroll/", api.enroll),
    path("runs/<int:pk>/checkout/", api.checkout),
    path("runs/<int:pk>/session/", api.run_session),
    path("sessions/<int:pk>/", api.session_detail),
    path("sessions/<int:pk>/prereq/", api.session_prereq),
    path("sessions/<int:pk>/start/", api.session_start),
    path("sessions/<int:pk>/help/", api.session_help),
    path("sessions/<int:pk>/final/", api.session_final),
    path("sessions/<int:pk>/build/", api.session_build),
    path("sessions/<int:pk>/transcript/", api.session_transcript),
    path("sessions/<int:pk>/agent/", api.session_agent),
    path("sessions/<int:pk>/agent/servers/", api.agent_servers),
    path("sessions/<int:pk>/agent/servers/<int:sid>/refresh/", api.agent_server_refresh),
    path("sessions/<int:pk>/agent/servers/<int:sid>/", api.agent_server_delete),
    path("sessions/<int:pk>/agent/run/", api.agent_run),
    path("sessions/<int:pk>/agent/approve/", api.agent_approve),
    path("sessions/<int:pk>/agent/reset/", api.agent_reset),
    path("mcp/", mcp_server.endpoint),  # Aasan Tools over MCP (per-session workshop token, not a JWT)
]

admin_urlpatterns = [
    path("workshops/", api.admin_workshops),
    path("workshops/runs/", admin_api.runs),
    path("workshops/runs/<int:pk>/", admin_api.run_detail),
    path("workshops/runs/<int:pk>/publish/", admin_api.run_publish),
    path("workshops/runs/<int:pk>/announce/", admin_api.run_announce),
    path("workshops/runs/<int:pk>/cancel/", admin_api.run_cancel),
    path("workshops/runs/<int:pk>/stats/", admin_api.run_stats),
    path("workshops/<slug:slug>/test-run/", api.admin_test_run),
    path("workshops/orgs/", admin_api.orgs),
    path("workshops/orgs/<int:pk>/", admin_api.org_detail),
]

# Included by apps/orgs/urls.py under /api/orgs/<slug>/workshops/ (institution workshops).
org_urlpatterns = [
    path("", org.overview),
    path("templates/", org.templates),
    path("runs/", org.runs),
    path("runs/<int:pk>/", org.run_detail),
    path("runs/<int:pk>/cancel/", org.run_cancel),
    path("runs/<int:pk>/learners/<int:session_id>/", org.learner_detail),
    path("runs/<int:pk>/report/", org.run_report),
    path("runs/<int:pk>/report.pdf", org.run_report_pdf),
    path("runs/<int:pk>/report.pptx", org.run_report_pptx),
    path("runs/<int:pk>/report.csv", org.run_report_csv),
]
