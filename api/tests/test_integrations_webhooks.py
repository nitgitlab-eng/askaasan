"""C2 outbound webhooks: URL vetting (https only, public DNS, never our own host), the secret shown once, HMAC-SHA256
over f"{ts}.{body}" (recomputed here), retries then dead, FetchRefused terminal, auto-disable after 20 dead deliveries
with admins told, every event fired from its real trigger with first names only (no emails), test ping, delivery log
and redelivery. DNS and the HTTPS transport are faked: no network."""

import hashlib
import hmac
import json

import pytest
from rest_framework.test import APIClient

from apps.game.models import Notification
from apps.integrations import events
from apps.integrations.models import OrgWebhook, WebhookDelivery
from apps.learning import safe_fetch
from apps.orgs.models import Assignment, Group
from apps.providers.crypto import decrypt
from tests.test_cred_certificates import complete, course
from tests.test_training_records import org, pass_org_workshop  # noqa: F401 — shared fixture

pytestmark = pytest.mark.django_db
HOOKS = "/api/orgs/acme/integrations/webhooks/"
ALL = ["member.joined", "assignment.completed", "course.completed", "certificate.issued", "workshop.passed"]


@pytest.fixture
def net(monkeypatch):
    """Fake DNS (public unless the host starts with 'internal') and a fake HTTPS receiver."""
    state = {"status": 200, "calls": [], "raise": None}

    def resolve(host):
        return ["10.0.0.7"] if host.startswith("internal") else ["93.184.216.34"]

    def post_transport(host, ip, path, body, headers, deadline, stop=None):
        state["calls"].append({"host": host, "ip": ip, "path": path, "body": body, "headers": headers})
        if state["raise"]:
            raise state["raise"]
        return safe_fetch.RawResponse(state["status"], {}, b"ok")

    monkeypatch.setattr(safe_fetch, "resolve", resolve)
    monkeypatch.setattr(safe_fetch, "post_transport", post_transport)
    return state


def make_hook(org, evs=ALL, url="https://hooks.example.com/aasan"):  # noqa: F811
    r = org["owner"].post(HOOKS, {"url": url, "events": evs}, format="json")
    assert r.status_code == 201, r.data
    return r.data


def test_url_vetting_refuses_unsafe_targets(org, net, settings):  # noqa: F811
    settings.FRONTEND_URL = "https://app.aasan.in"
    bad = {
        "http://hooks.example.com/x": "https_only",
        "https://localhost/x": "private_address",
        "https://10.0.0.1/x": "ip_not_allowed",
        "https://hooks.example.com:8443/x": "port_not_allowed",
        "https://internal.example.com/x": "unreachable",  # DNS answers a private address
        "https://app.aasan.in/api/x": "own_host",
        "https://user:pw@hooks.example.com/x": "bad_url",
    }
    for url, code in bad.items():
        r = org["owner"].post(HOOKS, {"url": url, "events": ["member.joined"]}, format="json")
        assert r.status_code == 400 and r.data["reason"] == code, (url, r.data)
    assert (
        org["owner"]
        .post(HOOKS, {"url": "https://ok.example.com", "events": ["x"]}, format="json")
        .status_code
        == 400
    )
    assert (
        org["teacher"]
        .post(HOOKS, {"url": "https://ok.example.com", "events": ALL}, format="json")
        .status_code
        == 403
    )
    assert org["kavya"][0].get(HOOKS).status_code == 403


def test_secret_shown_once_and_rotation(org, net):  # noqa: F811
    h = make_hook(org)
    assert h["secret"].startswith("whsec_")
    w = OrgWebhook.objects.get()
    assert decrypt(w.secret_enc) == h["secret"] and h["secret"] not in w.secret_enc
    assert "secret" not in str(org["owner"].get(HOOKS).data)
    r = org["owner"].post(f"{HOOKS}{w.id}/rotate-secret/")
    assert r.status_code == 200 and r.data["secret"] != h["secret"]
    assert decrypt(OrgWebhook.objects.get().secret_enc) == r.data["secret"]


def _verify(call, secret):
    hd = call["headers"]
    expected = hmac.new(
        secret.encode(), f"{hd['X-Aasan-Timestamp']}.".encode() + call["body"], hashlib.sha256
    )
    assert hd["X-Aasan-Signature"] == f"sha256={expected.hexdigest()}"
    return json.loads(call["body"])


def test_member_joined_signed_pinned_and_without_emails(org, net):  # noqa: F811
    h = make_hook(org)
    code = Group.objects.get(org=org["org"], name="B").join_code
    from tests.test_training_records import user

    c, u = user("newbie@acme.in", "Nila Devi")
    assert c.post(f"/api/orgs/join/{code}/").status_code == 200
    call = net["calls"][-1]
    assert call["host"] == "hooks.example.com" and call["ip"] == "93.184.216.34" and call["path"] == "/aasan"
    body = _verify(call, h["secret"])
    assert body["event"] == "member.joined" and call["headers"]["X-Aasan-Event"] == "member.joined"
    assert body["data"]["member"]["first_name"] == "Nila" and body["data"]["member"]["user_id"] == u.id
    assert body["org"] == {"slug": "acme", "name": "Acme Training"}
    assert "@" not in call["body"].decode()  # never an email address
    d = WebhookDelivery.objects.get(event="member.joined")
    assert d.status == "ok" and d.attempt == 1 and d.response_status == 200
    assert call["headers"]["X-Aasan-Delivery"] == str(d.id)


def test_course_assignment_and_certificate_events_from_lesson_completion(org, net):  # noqa: F811
    h = make_hook(org, ["assignment.completed", "course.completed", "certificate.issued"])
    owner = org["org"].memberships.get(role="owner").user
    kc, k = org["kavya"]
    cur, subs = course(owner, title="Fire safety", approved=False, learner=k)
    a = Assignment.objects.create(org=org["org"], curriculum=cur)
    complete(kc, subs)
    got = {json.loads(c["body"])["event"]: _verify(c, h["secret"]) for c in net["calls"]}
    assert set(got) == {"assignment.completed", "course.completed", "certificate.issued"}
    assert got["course.completed"]["data"]["course"] == {"id": cur.id, "title": "Fire safety"}
    assert got["assignment.completed"]["data"]["assignment"]["id"] == a.id
    assert got["certificate.issued"]["data"]["learner"]["user_id"] == k.id
    assert all("@" not in c["body"].decode() for c in net["calls"])
    n = len(net["calls"])
    complete(kc, subs[:1])  # finishing a lesson again tells nobody twice
    assert len(net["calls"]) == n


def test_workshop_passed_event(org, net):  # noqa: F811
    make_hook(org, ["workshop.passed"])
    run, _ = pass_org_workshop(org)
    bodies = [json.loads(c["body"]) for c in net["calls"]]
    assert [b["event"] for b in bodies] == ["workshop.passed"]
    assert bodies[0]["data"]["workshop"] == {"run_id": run.id, "title": run.workshop.title}


def test_unsubscribed_or_inactive_webhooks_get_nothing(org, net):  # noqa: F811
    h = make_hook(org, ["workshop.passed"])
    code = Group.objects.get(org=org["org"], name="B").join_code
    from tests.test_training_records import user

    assert user("a@acme.in", "A")[0].post(f"/api/orgs/join/{code}/").status_code == 200
    assert not net["calls"] and not WebhookDelivery.objects.exists()
    org["owner"].patch(f"{HOOKS}{h['id']}/", {"events": ["member.joined"], "active": False}, format="json")
    assert user("b@acme.in", "B")[0].post(f"/api/orgs/join/{code}/").status_code == 200
    assert not net["calls"]


def test_retries_with_backoff_then_dead(org, net):  # noqa: F811
    h = make_hook(org, ["member.joined"])
    net["raise"] = safe_fetch.FetchFailed("timeout")
    ids = events.emit(org["org"], "member.joined", {"x": 1})
    d = WebhookDelivery.objects.get(pk=ids[0])
    assert d.status == "failed" and d.attempt == 1 and d.next_try_at and d.last_error == "timeout"
    net["raise"], net["status"] = None, 503
    for i in range(2, events.MAX_TRIES + 1):
        d = events.attempt(d.id)
        assert d.attempt == i and d.response_status == 503
    assert d.status == "dead" and d.next_try_at is None and d.last_error == "http_503"
    assert events.attempt(d.id).attempt == events.MAX_TRIES  # dead stays dead
    w = OrgWebhook.objects.get(pk=h["id"])
    assert w.failures == 1 and w.active


def test_retry_due_picks_up_failed_deliveries(org, net):  # noqa: F811
    make_hook(org, ["member.joined"])
    net["status"] = 500
    (did,) = events.emit(org["org"], "member.joined", {})
    WebhookDelivery.objects.filter(pk=did).update(next_try_at="2000-01-01T00:00:00Z")
    net["status"] = 200
    assert events.retry_due() == 1
    assert WebhookDelivery.objects.get(pk=did).status == "ok"


def test_refused_url_is_dead_at_once(org, net):  # noqa: F811
    h = make_hook(org, ["member.joined"])
    OrgWebhook.objects.filter(pk=h["id"]).update(
        url="http://hooks.example.com/aasan"
    )  # e.g. edited in the DB
    (did,) = events.emit(org["org"], "member.joined", {})
    d = WebhookDelivery.objects.get(pk=did)
    assert d.status == "dead" and d.attempt == 1 and d.last_error == "https_only" and not net["calls"]


def test_auto_disable_after_twenty_dead_and_admins_told(org, net):  # noqa: F811
    h = make_hook(org, ["member.joined"])
    OrgWebhook.objects.filter(pk=h["id"]).update(failures=19)
    net["raise"] = safe_fetch.FetchRefused("too_large")
    events.emit(org["org"], "member.joined", {})
    w = OrgWebhook.objects.get(pk=h["id"])
    assert not w.active and w.failures == 20 and w.disabled_reason == "too_many_failures"
    assert Notification.objects.filter(kind="webhook", user__email="owner@acme.in").exists()
    assert not Notification.objects.filter(kind="webhook", user__email="teach@acme.in").exists()
    assert events.emit(org["org"], "member.joined", {}) == []  # switched off: nothing queued
    r = org["owner"].patch(f"{HOOKS}{w.id}/", {"active": True}, format="json")
    assert r.data["active"] and r.data["failures"] == 0


def test_success_resets_the_failure_streak(org, net):  # noqa: F811
    h = make_hook(org, ["member.joined"])
    OrgWebhook.objects.filter(pk=h["id"]).update(failures=7)
    events.emit(org["org"], "member.joined", {})
    assert OrgWebhook.objects.get().failures == 0


def test_ping_delivery_log_and_redeliver(org, net):  # noqa: F811
    h = make_hook(org, ["member.joined"])
    r = org["owner"].post(f"{HOOKS}{h['id']}/test/")
    assert r.status_code == 200 and r.data["status"] == "ok" and r.data["event"] == "ping"
    _verify(net["calls"][-1], h["secret"])
    net["status"] = 500
    assert org["owner"].post(f"{HOOKS}{h['id']}/test/").data["status"] == "dead"  # a ping is never retried
    assert OrgWebhook.objects.get().failures == 0  # and never counts towards auto-disable
    (did,) = events.emit(org["org"], "member.joined", {"n": 1})
    log = org["owner"].get(f"{HOOKS}{h['id']}/deliveries/")
    assert log.status_code == 200 and log.data["count"] == 3 and log.data["results"][0]["id"] == did
    net["status"] = 200
    r = org["owner"].post(f"{HOOKS}{h['id']}/deliveries/{did}/redeliver/")
    assert r.status_code == 201 and r.data["status"] == "ok"
    first, again = (json.loads(c["body"]) for c in net["calls"][-2:])
    assert first["id"] == again["id"]  # same payload id: receivers can de-duplicate
    csv_body = org["owner"].get(f"{HOOKS}{h['id']}/deliveries/", {"export": "csv"}).content.decode()
    assert csv_body.startswith("id,event,status")
    assert APIClient().post(f"{HOOKS}{h['id']}/test/").status_code == 401


def test_ping_is_throttled(org, net):  # noqa: F811
    h = make_hook(org, ["member.joined"])
    codes = [org["owner"].post(f"{HOOKS}{h['id']}/test/").status_code for _ in range(11)]
    assert codes[:10] == [200] * 10 and codes[10] == 429


def test_cleanup_drops_old_deliveries(org, net, settings):  # noqa: F811
    from datetime import timedelta

    from django.utils import timezone

    make_hook(org, ["member.joined"])
    old, new = (events.emit(org["org"], "member.joined", {})[0] for _ in range(2))
    WebhookDelivery.objects.filter(pk=old).update(created_at=timezone.now() - timedelta(days=31))
    assert events.cleanup() == 1 and WebhookDelivery.objects.filter(pk=new).exists()
