"""Access sweep over every API route (any new endpoint is covered automatically).

1. Signed out: only PUBLIC routes may answer 2xx.
2. Signed in as an ordinary learner (no org role, not staff, not a creator): only LEARNER routes
   (the learner's own data) may answer 2xx — every admin, staff, creator, cockpit and org-admin route must refuse.
If this fails after adding an endpoint, check its permissions first; extend an allowlist only when it is meant to be open.
"""

import re

import pytest
from django.urls import get_resolver
from django.urls.resolvers import URLPattern, URLResolver
from rest_framework.test import APIClient

METHODS = ("get", "post", "put", "patch", "delete")
SKIP = ("logout", "account/delete", "users/me/delete")  # would end the sweep's own session

PUBLIC = {
    "api/health/",
    "api/legal/site/",
    "api/legal/subprocessors/",
    "api/support/articles/",
    "api/django-admin/login/",  # Django's own staff login form
    "api/users/logout/",
    "api/users/auth-config/",  # the login page needs the (public) Google client ID before anyone is signed in
    "api/users/email-verification/request/",  # signed out it re-mails only an unverified account at `email`, always 204
    "api/users/passkey/authenticate/begin/",
    "api/users/push/opened/",  # the service worker's "notification tapped" ping: no credentials, always 204
    "api/users/password-reset/request/",
    "api/guests/unsubscribe/",  # guest campaigns: one-click opt-out (signed token; public guest pages 404 on unknown slugs)
    "api/credentials/verify/<str:code>/",  # public certificate verification (404 unless the code is real and visible)
    "api/.well-known/oauth-authorization-server",
    "api/.well-known/oauth-protected-resource",  # Connect Claude: OAuth metadata
}

LEARNER = PUBLIC | {
    "api/credentials/",  # the learner's own certificates
    "api/guests/claim/",  # attach the caller's own guest progress (needs their guest token)
    "api/study/about/",
    "api/study/checkpoints/",
    "api/users/passkeys/",  # Milestone 8: own profile answers, tests, passkeys
    "api/users/push/",  # A1: is web push available + does the learner have a device
    "api/users/push/reminders/resume/",  # the learner resumes their own backed-off reminders
    "api/study/course-order/",  # Milestone 9: the learner's own course order on /learn
    "api/assistant/conversations/",
    "api/billing/",
    "api/billing/failed/",
    "api/billing/family/",  # the learner's own family plan state
    "api/billing/history/",
    "api/billing/subscription/",
    "api/calendar/",  # intg: own auto-renew status + own calendar connections
    "api/catalog/",
    "api/django-admin/login/",
    "api/docs/",
    "api/ext/devices/",
    "api/ext/pair/start/",  # the learner's own browser-extension pairing + devices
    "api/game/achievements/",
    "api/game/calendar-feed/",
    "api/game/leaderboard/",
    "api/game/notifications/",
    "api/game/notifications/read/",
    "api/game/nudges/",
    "api/game/plan.ics",
    "api/game/plan/",
    "api/game/settings/",
    "api/game/shop/",
    "api/game/status/",
    "api/health/",
    "api/journeys/me/",  # jr: the learner's own onboarding journeys
    "api/learn/continue/",
    "api/learn/curriculums/",
    "api/legal/export/",
    "api/legal/site/",
    "api/legal/subprocessors/",
    "api/live/sessions/",
    "api/orgs/",
    "api/orgs/me/assignments/",
    "api/workshops/runs/",  # ws: public workshop runs + the learner's own
    "api/orgs/me/brand/",
    "api/orgs/me/documents/",
    "api/orgs/me/fields/",
    "api/orgs/me/cohorts/",  # Milestone 9: own member fields + own cohort courses
    "api/orgs/me/surveys/",
    "api/orgs/me/training-record/",  # C3: the learner's own training record (+ Excel / PDF)
    "api/orgs/me/training-record.xlsx",
    "api/orgs/me/training-record.pdf",
    "api/orgs/survey-templates/",
    "api/paths/careers/",
    "api/paths/curated/",
    "api/paths/onboarding-apply/",
    "api/paths/onboarding-chat/",
    "api/paths/recommendations/",
    "api/paths/skills/",
    "api/paths/skills/bulk/",
    "api/paths/skills/reorder/",
    "api/review/overview/",
    "api/review/session/",
    "api/roleplay/scenarios/",
    "api/roleplay/sessions/",
    "api/studio/exports/progress.xlsx",
    "api/studio/review/",
    "api/studio/templates/",
    "api/study/blocks/",
    "api/study/buddies/",
    "api/study/buddies/<int:pk>/",
    "api/study/pauses/",
    "api/study/progress/",
    "api/study/progress/insights/",
    "api/study/revision-board/",
    "api/study/today/",
    "api/study/today/focus/",
    "api/support/articles/",
    "api/support/reports/",
    "api/users/guardian/",
    "api/users/me/",
    "api/users/passkey/authenticate/begin/",
    "api/users/passkey/register/begin/",
    "api/users/password-reset/request/",
    "api/users/preferences/",
    "api/users/profile/",
    "api/users/refresh-token/",
    "api/voice/config/",
}


def _routes(patterns=None, prefix=""):
    for p in get_resolver().url_patterns if patterns is None else patterns:
        if isinstance(p, URLResolver):
            yield from _routes(p.url_patterns, prefix + str(p.pattern))
        elif isinstance(p, URLPattern):
            route = prefix + str(p.pattern)
            if route.startswith("api/"):
                yield route


def _path(route):
    return "/" + re.sub(r"<(?:\w+:)?\w+>", "1", route).replace("^", "").replace("$", "")


def _sweep(c, allowed):
    leaks = []
    for route in sorted(set(_routes())):
        if any(s in route for s in SKIP) and route not in allowed:
            continue
        for m in METHODS:
            r = c.get(_path(route)) if m == "get" else getattr(c, m)(_path(route), {}, format="json")
            if 200 <= r.status_code < 300 and route not in allowed:
                leaks.append(f"{m.upper()} {route} -> {r.status_code}")
    return leaks


@pytest.mark.django_db
def test_signed_out_reaches_only_public_routes():
    assert _sweep(APIClient(), PUBLIC) == []


@pytest.mark.django_db
def test_learner_cannot_reach_privileged_routes(auth):
    c, _ = auth
    assert _sweep(c, LEARNER) == []
