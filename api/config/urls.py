import os

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from apps.accounts import console_urls
from apps.accounts.guardian import guardian_consent, guardian_stop, guardian_view
from apps.accounts.views import guard_admin_login
from apps.billing import urls as billing_urls
from apps.calsync import urls as calsync_urls
from apps.connect import urls as connect_urls
from apps.integrations.urls import v1_urlpatterns
from apps.learning import lab_urls
from apps.legal import urls as legal_urls
from apps.providers.urls import admin_urlpatterns, voice_urlpatterns
from apps.support import urls as support_urls
from apps.workshops import urls as workshop_urls

# The admin's password form shares the API login's per-account lockout (must be set before admin.site.urls is built).
if not getattr(admin.site.login, "lockout_guarded", False):
    admin.site.login = guard_admin_login(admin.site.login)

urlpatterns = [
    # Django's own admin lives under /api/ so the Aasan admin console can own /admin in the browser.
    # An empty DJANGO_ADMIN_PATH means the default, never the site root.
    path(os.environ.get("DJANGO_ADMIN_PATH") or "api/django-admin/", admin.site.urls),
    path("api/health/", lambda r: JsonResponse({"ok": True})),
    path("api/users/", include("apps.accounts.urls")),
    path("api/assistant/", include("apps.mentor.urls")),
    path(
        "api/admin/",
        include(
            admin_urlpatterns
            + lab_urls.admin_urlpatterns
            + billing_urls.admin_urlpatterns
            + legal_urls.admin_urlpatterns
            + support_urls.admin_urlpatterns
            + calsync_urls.admin_urlpatterns
            + workshop_urls.admin_urlpatterns
            + console_urls.admin_urlpatterns
        ),
    ),
    path("api/lab/", include(lab_urls.urlpatterns)),
    path("api/catalog/", include(lab_urls.catalog_urlpatterns)),
    path("api/share/", include(lab_urls.share_urlpatterns)),
    path("api/roleplay/", include("apps.roleplay.urls")),
    path("api/orgs/", include("apps.orgs.urls")),
    path("api/billing/", include(billing_urls.urlpatterns)),
    path("api/legal/", include(legal_urls.urlpatterns)),
    path("api/live/", include("apps.live.urls")),
    path("api/media/", include("apps.media.urls")),
    path("api/paths/", include("apps.paths.urls")),
    path("api/study/", include("apps.study.urls")),
    path("api/studio/", include("apps.studio.urls")),
    path("api/support/", include("apps.support.urls")),
    path("api/guardian/<str:token>/", guardian_view),
    path("api/guardian/<str:token>/stop/", guardian_stop),
    path("api/guardian/<str:token>/consent/", guardian_consent),
    path("api/voice/", include(voice_urlpatterns)),
    path("api/learn/", include("apps.learning.urls")),
    path("api/review/", include("apps.review.urls")),
    path("api/game/", include("apps.game.urls")),
    path("api/docs/", include("apps.docs.urls")),
    path("api/ext/", include("apps.extension.urls")),
    path("api/guests/", include("apps.guests.urls")),
    path("api/credentials/", include("apps.credentials.urls")),
    path("api/connect/", include(connect_urls.urlpatterns)),
    *connect_urls.root_urlpatterns,  # /api/mcp + OAuth metadata (see apps/connect/urls.py)
    path("api/calendar/", include(calsync_urls.urlpatterns)),
    path("api/journeys/", include("apps.journeys.urls")),
    path("api/adaptive/", include("apps.adaptive.urls")),
    path("api/workshops/", include(workshop_urls.urlpatterns)),
    path("api/v1/orgs/<slug:slug>/", include(v1_urlpatterns)),  # organisation API: API keys only
]
