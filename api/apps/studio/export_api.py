"""Download endpoints for M6 exports + the learner's quarterly review (P2)."""

from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.accounts.staff import AdminSection
from apps.learning.models import Curriculum

from . import exports


def _deck_course(request, pk) -> Curriculum:
    """Decks include answer keys: the course's author, or staff of the org whose own template it is (same rule as
    orgs.teach.can_see_keys). Assigning someone else's course to a class never unlocks its keys. Org-wide staff only:
    unit-scoped admins are not (perms.staff_org_ids, the rule require(..., 'manager') applies on the teach key views)."""
    from apps.orgs.perms import staff_org_ids

    cur = get_object_or_404(Curriculum, pk=pk)
    if cur.owner_id == request.user.id:
        return cur
    if (
        cur.template_scope == "org"
        and cur.template_org_id
        and cur.template_org_id in set(staff_org_ids(request.user))
    ):
        return cur
    from django.http import Http404

    raise Http404


@api_view(["GET"])
def course_pptx(request, pk):
    cur = _deck_course(request, pk)
    lessons = None
    if raw := request.query_params.get("lesson"):
        try:
            lessons = {int(raw)}
        except ValueError:
            return Response({"code": "bad_lesson"}, status=status.HTTP_400_BAD_REQUEST)
    return exports.download(
        exports.deck(cur, lessons), exports.PPTX, exports._fname(cur.title or cur.goal, "pptx")
    )


@api_view(["GET"])
def org_analytics_xlsx(request, slug):
    from apps.orgs.perms import require

    me = require(request.user, slug, "manager")
    return exports.download(
        exports.org_analytics_xlsx(me.org), exports.XLSX, exports._fname(f"{me.org.name} analytics", "xlsx")
    )


@api_view(["GET"])
def survey_xlsx(request, slug, pk):
    from apps.orgs.models import Survey
    from apps.orgs.perms import require

    me = require(request.user, slug, "manager")
    s = get_object_or_404(Survey, pk=pk, org=me.org)
    return exports.download(exports.survey_xlsx(s), exports.XLSX, exports._fname(f"survey {s.title}", "xlsx"))


@api_view(["GET"])
@permission_classes([AdminSection])
def admin_overview_xlsx(request):
    from apps.providers.overview import overview

    data = overview(request._request).data  # same numbers (and staff check) as the console page
    return exports.download(exports.generic_workbook("Overview", data), exports.XLSX, "aasan-overview.xlsx")


@api_view(["GET"])
def progress_xlsx(request):
    from apps.study.progress import _days_param

    days = _days_param(request.query_params.get("days"), 90)
    return exports.download(
        exports.progress_xlsx(request.user, days), exports.XLSX, f"my-progress-{days}d.xlsx"
    )


# ── Quarterly review ─────────────────────────────────────────────────


def _quarter(d=None):
    d = d or timezone.localdate()
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def _review_facts(user) -> dict:
    from apps.learning.models import UserSubsectionState
    from apps.study.progress import dashboard

    d = dashboard(user, 90)
    since = timezone.now() - timedelta(days=90)
    done = UserSubsectionState.objects.filter(
        user=user, status="completed", completed_at__gte=since
    ).select_related("subsection__section__curriculum")
    courses: dict[str, list[str]] = {}
    for st in done:
        courses.setdefault(st.subsection.section.curriculum.title, []).append(st.subsection.title)
    return {
        "totals": d["totals"],
        "courses": {k: v[:12] for k, v in list(courses.items())[:12]},
        "skills": [
            {"name": s["name"], "mastery_pct": None if s["mastery"] is None else round(s["mastery"] * 100)}
            for s in d["skills"][:15]
        ],
        "accuracy_by_type": d["efficiency"][:8],
    }


@api_view(["GET", "POST"])
def quarterly_review(request):
    """GET: cached review for this quarter (or null). POST: write it (AI, once per quarter + language)."""
    import json

    from apps.learning.services import content_language
    from apps.study.models import ProgressInsight
    from llm.base import LLMError
    from llm.prompts.curriculum import LANG_RULE
    from llm.prompts.studio import REVIEW_SYSTEM, Review
    from llm.structured import complete_json_sync

    lang = content_language(request.user)
    key = _quarter()
    cached = ProgressInsight.objects.filter(user=request.user, week=key, lang=lang).first()
    if request.method == "GET" or cached:
        return Response(
            {
                "quarter": key,
                "review": cached.data["review"] if cached else None,
                "facts": cached.data["facts"] if cached else None,
            }
        )
    from apps.study.progress import _ai_charge

    if denied := _ai_charge(request.user):
        return denied
    facts = _review_facts(request.user)
    try:
        out = complete_json_sync(
            "suggest",
            REVIEW_SYSTEM.format(lang_rule=LANG_RULE.get(lang, LANG_RULE["en"])),
            json.dumps(facts, default=str, ensure_ascii=False),
            Review,
            max_tokens=2000,
        )
    except LLMError as e:
        return Response({"code": e.code}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    data = {"review": out.model_dump(), "facts": json.loads(json.dumps(facts, default=str))}
    ProgressInsight.objects.update_or_create(user=request.user, week=key, lang=lang, defaults={"data": data})
    return Response({"quarter": key, **data}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def quarterly_review_xlsx(request):
    from apps.learning.services import content_language
    from apps.study.models import ProgressInsight

    rec = ProgressInsight.objects.filter(
        user=request.user, week=_quarter(), lang=content_language(request.user)
    ).first()
    if not rec:
        return Response({"code": "no_review"}, status=status.HTTP_404_NOT_FOUND)
    r, f = rec.data["review"], rec.data["facts"]
    rows = [
        ["Title", r["title"]],
        ["Overview", r["overview"]],
        *[["Covered", x] for x in r["covered"]],
        *[["Mastered", x] for x in r["mastered"]],
        *[["Grow next", x] for x in r["growth"]],
        *[["Next quarter goal", x] for x in r["next_quarter"]],
    ]
    body = exports.workbook(
        [
            ("Review", ["Section", "Text"], rows),
            ("Numbers", ["Metric", "Value"], [[k, v] for k, v in f["totals"].items()]),
            (
                "Courses",
                ["Course", "Lessons completed"],
                [[c, ", ".join(ls)] for c, ls in f["courses"].items()],
            ),
            ("Skills", ["Skill", "Mastery %"], [[s["name"], s["mastery_pct"]] for s in f["skills"]]),
        ]
    )
    return exports.download(body, exports.XLSX, f"aasan-review-{_quarter()}.xlsx")
