"""M10 rca: live-observation steps for browser tasks — author-only step editing + validation, glob matching, and the
extension's observed-step evidence re-validated on submit (before any AI spend)."""

import json
from pathlib import Path

import pytest
from rest_framework.test import APIClient

from apps.extension import steps as obs
from apps.extension.models import ObservedSteps
from apps.learning.models import ActivityAttempt
from apps.providers.models import UsageCounter
from tests.test_extension import course, jwt_client, learner, pair, png_data_url  # noqa: F401 — fixtures

pytestmark = pytest.mark.django_db

STEPS = [
    {"label": "Open a new sheet", "url_pattern": "https://docs.google.com/spreadsheets/*"},
    {
        "label": "Show the total",
        "url_pattern": "https://*.google.com/spreadsheets/d/*/edit*",
        "text": "  Total  ",
    },
]


def owner_client(course):  # noqa: F811
    cur = course[0]
    c = APIClient()
    c.force_authenticate(cur.owner)
    return c


# ── Pure matching / validation ───────────────────────────────────────


@pytest.mark.parametrize(
    "url,pattern,ok",
    [
        ("https://docs.google.com/spreadsheets/d/1/edit", "https://docs.google.com/spreadsheets/*", True),
        ("https://docs.google.com/document/d/1", "https://docs.google.com/spreadsheets/*", False),
        ("https://sheets.docs.google.com/spreadsheets/x", "https://*.google.com/spreadsheets/*", True),
        ("https://google.com/spreadsheets/x", "https://*.google.com/spreadsheets/*", True),
        ("https://evil-google.com/spreadsheets/x", "https://*.google.com/spreadsheets/*", False),
        (
            "https://evil.com/x.google.com/spreadsheets/",
            "https://*.google.com/*",
            False,
        ),  # * never reaches into the host
        ("https://docs.google.com.evil.com/spreadsheets/", "https://docs.google.com/*", False),
        ("http://docs.google.com/spreadsheets/", "https://docs.google.com/*", False),  # https only
        ("https://user:pw@docs.google.com/", "https://docs.google.com/*", False),
        ("https://docs.google.com:8443/", "https://docs.google.com/*", False),
        ("https://DOCS.google.com/a#frag", "https://docs.google.com/a", True),
        ("https://chatgpt.com/c/1?q=hello", "https://chatgpt.com/c/*", True),  # query ignored
        (
            "https://evil.com\\x.google.com/a",
            "https://*.google.com/*",
            False,
        ),  # browsers read the host as evil.com
        ("https://evil.com\\@docs.google.com/", "https://docs.google.com/*", False),
        ("https://docs.google.com/a b", "https://docs.google.com/*", False),
        ("https://docs.google.com/\ta", "https://docs.google.com/*", False),
        ("https://a.foo.co.in/x", "https://*.foo.co.in/*", True),
        ("https://chatgpt.com/anything", "https://chatgpt.com", True),
        ("javascript:alert(1)", "https://chatgpt.com", False),
        ("https://x.com/[a]", "https://x.com/[a]", True),  # brackets are literal, not a character class
    ],
)
def test_url_matches(url, pattern, ok):
    assert obs.url_matches(url, pattern) is ok


@pytest.mark.parametrize(
    "bad",
    [
        [{"label": "", "url_pattern": "https://a.com/*"}],
        [{"label": "x", "url_pattern": "http://a.com/*"}],
        [{"label": "x", "url_pattern": "https://*/*"}],
        [{"label": "x", "url_pattern": "https://*.com/*"}],
        [{"label": "x", "url_pattern": "https://chatgpt.com?q=*"}],  # no queries in patterns
        [{"label": "x", "url_pattern": "https://chatgpt.com/a#b"}],
        [{"label": "x", "url_pattern": "https://a.com\\b.com/*"}],
        *(
            [{"label": "x", "url_pattern": f"https://*.{sfx}/*"}]
            for sfx in (
                "co.in",
                "net.in",
                "ac.in",
                "gov.in",
                "co.uk",
                "com.au",
                "github.io",
                "gitlab.io",
                "blogspot.com",
                "netlify.app",
                "vercel.app",
                "pages.dev",
                "web.app",
                "herokuapp.com",
                "appspot.com",
                "CO.IN",
                "in",
                "io",
            )
        ),
        [{"label": "x", "url_pattern": "https://a*.com/*"}],
        [{"label": "x", "url_pattern": "https://localhost/*"}],
        [{"label": "x", "url_pattern": "https://a.com:99/*"}],
        [{"label": "x", "url_pattern": "https://a.com/*", "text": "y" * 81}],
        [{"label": "x" * 121, "url_pattern": "https://a.com/*"}],
        [{"label": "x", "url_pattern": "https://a.com/*"}] * 9,
        "nope",
        ["nope"],
    ],
)
def test_validate_rejects(bad):
    with pytest.raises(obs.StepError):
        obs.validate(bad)


def test_validate_normalises_and_permission_origins():
    steps = obs.validate(STEPS)
    assert [s["id"] for s in steps] == ["s1", "s2"] and steps[1]["text"] == "Total"
    assert obs.hosts(steps) == ["docs.google.com", "*.google.com"]
    assert obs.origins(steps) == [
        "https://docs.google.com/*",
        "https://*.google.com/*",
    ]  # exactly these, never <all_urls>


# ── Authoring endpoint ───────────────────────────────────────────────


def test_author_sets_steps_others_refused(course, learner):  # noqa: F811
    _, _, a = course
    url = f"/api/ext/authoring/activities/{a.id}/steps/"
    oc = owner_client(course)
    assert oc.get(url).data == {"steps": [], "hosts": [], "origins": [], "optional": False}
    r = oc.put(url, {"steps": STEPS}, format="json")
    assert r.status_code == 200 and r.data["hosts"] == ["docs.google.com", "*.google.com"]
    bad = oc.put(url, {"steps": [{"label": "x", "url_pattern": "https://*/*"}]}, format="json")
    assert (
        bad.status_code == 400 and bad.data["code"] == "invalid_steps" and bad.data["field"] == "url_pattern"
    )
    assert len(ObservedSteps.objects.get(activity=a).steps) == 2  # unchanged by the bad PUT
    # a learner of the course, another creator, signed-out and the extension token are all refused
    lc, _ = learner
    assert lc.get(url).status_code == 404 and lc.put(url, {"steps": []}, format="json").status_code == 404
    other, _ = jwt_client("other-teacher@aasan.test")
    assert other.put(url, {"steps": STEPS}, format="json").status_code == 404
    assert APIClient().get(url).status_code in (401, 403)
    ext, _ = pair(lc)
    assert ext.get(url).status_code in (401, 403)
    # the Lab can still edit the activity (steps aren't in the strict source schema)
    assert oc.patch(
        f"/api/lab/activities/{a.id}/", {"source": {**a.source, "title": "Sum it!"}}, format="json"
    ).status_code in (200, 403)
    assert ObservedSteps.objects.filter(activity=a).exists()
    assert oc.put(url, {"steps": []}, format="json").data["steps"] == []
    assert not ObservedSteps.objects.filter(activity=a).exists()


# ── Task list + submit with evidence ────────────────────────────────


def _evidence(**over):
    ev = [
        {"step": "s1", "url": "https://docs.google.com/spreadsheets/u/0/", "title": "Sheets"},
        {
            "step": "s2",
            "url": "https://docs.google.com/spreadsheets/d/abc/edit#gid=0",
            "title": "Budget",
            "text_found": True,
        },
    ]
    for i, v in over.items():
        ev[int(i[1:]) - 1] = {**ev[int(i[1:]) - 1], **v}
    return ev


def test_tasks_list_steps_and_submit_validates_evidence(course, learner):  # noqa: F811
    _, _, a = course
    owner_client(course).put(f"/api/ext/authoring/activities/{a.id}/steps/", {"steps": STEPS}, format="json")
    c, u = learner
    ext, _ = pair(c)
    t = ext.get("/api/ext/tasks/").data["tasks"][0]
    assert (
        t["observe"]["origins"] == ["https://docs.google.com/*", "https://*.google.com/*"]
        and len(t["observe"]["steps"]) == 2
    )
    assert t["observe"]["optional"] is False
    assert "SECRET" not in str(t)
    sub = f"/api/ext/tasks/{a.id}/submit/"
    final = "https://docs.google.com/spreadsheets/d/abc/edit"

    def post(observed, url=final):
        return ext.post(
            sub, {"url": url, "title": "Budget", "image": png_data_url(), "observed": observed}, format="json"
        )

    assert post(_evidence()[:1]).data["code"] == "steps_incomplete"
    assert post(list(reversed(_evidence()))).data["code"] == "steps_mismatch"
    r = post(_evidence(s1={"url": "https://evil.com/docs.google.com/spreadsheets/"}))
    assert r.status_code == 422 and r.data == {"code": "step_url_mismatch", "step": "s1"}
    assert post(_evidence(s2={"text_found": False})).data["code"] == "step_text_missing"
    assert post(_evidence(s2={"text_found": "yes"})).data["code"] == "step_text_missing"
    assert post(_evidence(), url="https://example.com/").data["code"] == "wrong_site"
    assert post("nope").status_code == 400
    assert not UsageCounter.objects.filter(user=u, metric="ai_grades").exists()  # no AI spend on any of these
    ok = post(_evidence())
    assert ok.status_code == 200 and ok.data["score"] == 0.9
    at = ActivityAttempt.objects.get(user=u, activity=a)
    assert [e["step"] for e in at.answer["observed"]] == ["s1", "s2"] and at.answer["observed"][1][
        "text_found"
    ] is True
    # without evidence: refused while the steps are required (default), accepted once the author marks them optional
    plain = ext.post(sub, {"url": final, "image": png_data_url()}, format="json")
    assert plain.status_code == 422 and plain.data["code"] == "steps_required"
    r = owner_client(course).put(
        f"/api/ext/authoring/activities/{a.id}/steps/", {"steps": STEPS, "optional": True}, format="json"
    )
    assert r.data["optional"] is True  # (the task left the open list: it was passed above)
    assert ext.post(sub, {"url": final, "image": png_data_url()}, format="json").status_code == 200
    bad = owner_client(course).put(
        f"/api/ext/authoring/activities/{a.id}/steps/", {"steps": STEPS, "optional": "yes"}, format="json"
    )
    assert bad.status_code == 400


def test_evidence_urls_stripped_titles_capped_and_grader_told_unverified(course, learner, monkeypatch):  # noqa: F811
    _, _, a = course
    owner_client(course).put(f"/api/ext/authoring/activities/{a.id}/steps/", {"steps": STEPS}, format="json")
    c, u = learner
    ext, _ = pair(c)
    seen = {}
    from apps.learning import activities as acts

    real = acts.grade

    def spy(activity, answer, lang, user=None):
        seen["text"] = answer["text"]
        return real(activity, answer, lang, user=user)

    monkeypatch.setattr(acts, "grade", spy)
    ev = _evidence(
        s1={"url": "https://docs.google.com/spreadsheets/u/0/?token=SECRET123#x", "title": "T" * 500},
        s2={"url": "https://docs.google.com/spreadsheets/d/abc/edit?usp=SECRET456#gid=0"},
    )
    sub = f"/api/ext/tasks/{a.id}/submit/"
    r = ext.post(
        sub,
        {"url": "https://docs.google.com/spreadsheets/d/abc/edit", "image": png_data_url(), "observed": ev},
        format="json",
    )
    assert r.status_code == 200, r.data
    stored = ActivityAttempt.objects.get(user=u, activity=a).answer["observed"]
    assert (
        stored[0]["url"] == "https://docs.google.com/spreadsheets/u/0/"
        and stored[1]["url"] == "https://docs.google.com/spreadsheets/d/abc/edit"
    )
    assert len(stored[0]["title"]) == 120 and "SECRET" not in json.dumps(stored)
    assert "CLIENT-REPORTED" in seen["text"] and "unverified" in seen["text"] and "SECRET" not in seen["text"]
    # backslash in an evidence URL or in the final URL is refused before any AI spend
    n = UsageCounter.objects.get(user=u, metric="ai_grades").amount
    bs = _evidence(s1={"url": "https://evil.com\\docs.google.com/spreadsheets/x"})
    assert (
        ext.post(
            sub,
            {
                "url": "https://docs.google.com/spreadsheets/d/abc/edit",
                "image": png_data_url(),
                "observed": bs,
            },
            format="json",
        ).data["code"]
        == "step_url_mismatch"
    )
    assert (
        ext.post(
            sub,
            {
                "url": "https://evil.com\\x.google.com/spreadsheets/d/abc/edit",
                "image": png_data_url(),
                "observed": _evidence(),
            },
            format="json",
        ).data["code"]
        == "bad_url"
    )
    assert UsageCounter.objects.get(user=u, metric="ai_grades").amount == n


def test_public_suffix_list_identical_in_extension_and_api():
    root = Path(__file__).resolve().parents[2]
    ext = json.loads((root / "extension" / "public_suffixes.json").read_text())
    api = json.loads((root / "api" / "apps" / "extension" / "public_suffixes.json").read_text())
    assert ext == api and {"co.in", "github.io", "blogspot.com", "co.uk"} <= set(api["suffixes"])
    assert obs.PUBLIC_SUFFIXES == frozenset(api["suffixes"])


def test_evidence_for_task_without_steps_or_not_viewable(course, learner):  # noqa: F811
    _, _, a = course
    c, _ = learner
    ext, _ = pair(c)
    r = ext.post(
        f"/api/ext/tasks/{a.id}/submit/",
        {"url": "https://docs.google.com/x", "image": png_data_url(), "observed": _evidence()},
        format="json",
    )
    assert r.status_code == 422 and r.data["code"] == "steps_mismatch"
    # another learner's private course task: not visible → 404, steps or not
    from apps.learning import activities as acts
    from apps.learning.models import Activity, Curriculum, Section, Subsection
    from tests.test_extension import TASK

    _, stranger = jwt_client("stranger@aasan.test")
    cur = Curriculum.objects.create(
        owner=stranger, kind=Curriculum.Kind.AUTHORED, goal="g", title="Private", status="ready"
    )
    sub = Subsection.objects.create(
        section=Section.objects.create(curriculum=cur, order=0, title="S"), order=0, title="L", objective="o"
    )
    payload, key = acts.build(TASK, seed=2)
    priv = Activity.objects.create(
        subsection=sub, order=0, type="browser_task", title="t", payload=payload, key=key, source=dict(TASK)
    )
    ObservedSteps.objects.create(activity=priv, steps=obs.validate(STEPS))
    r = ext.post(
        f"/api/ext/tasks/{priv.id}/submit/",
        {
            "url": "https://docs.google.com/spreadsheets/d/abc/edit",
            "image": png_data_url(),
            "observed": _evidence(),
        },
        format="json",
    )
    assert r.status_code == 404
    assert c.get(f"/api/ext/authoring/activities/{priv.id}/steps/").status_code == 404
