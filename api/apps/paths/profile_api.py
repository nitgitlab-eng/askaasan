"""Smart-onboarding extras and career goals: company lookup, role summary, CV upload, free-text target role."""

from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, throttle_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from .models import Skill, UserSkill
from .services import match_skills

CV_MAX_BYTES = 5 * 1024 * 1024


class CVThrottle(UserRateThrottle):
    scope, rate = "paths_cv", "10/hour"


def _charge(user, metric, limit):
    from apps.providers.services import BudgetExceeded, charge

    try:
        charge(user, metric, 1, limit)
        return None
    except BudgetExceeded:
        return Response({"code": "daily_limit"}, status=status.HTTP_429_TOO_MANY_REQUESTS)


def _remember(user, **kw):
    from apps.study.about import about_of

    a = about_of(user)
    a.data = {**a.data, **{k: v for k, v in kw.items() if v not in (None, "")}}
    a.save()


def _skills_out(names):
    slugs = match_skills(names)
    return [
        {"slug": s.slug, "name": s.name, "name_ta": s.name_ta}
        for s in Skill.objects.filter(slug__in=slugs, active=True)
    ]


@api_view(["POST"])
def company(request):
    """Where do you work / study? → a short AI summary from web research (shown for the learner to confirm)."""
    from llm.prompts.paths import COMPANY_SYSTEM, CompanySummary
    from llm.research import research
    from llm.structured import complete_json_sync

    name = str(request.data.get("name") or "").strip()[:120]
    if len(name) < 2:
        return Response({"code": "name_required"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, "research", 5):
        return denied
    try:
        r = research(
            f"{name} (organisation, India)",
            "What the organisation does, its industry, and skills its people use.",
        )
        out = complete_json_sync(
            "utility",
            COMPANY_SYSTEM,
            f"Organisation: {name}\n\nResearch notes:\n{r['notes'][:5000]}",
            CompanySummary,
            max_tokens=800,
        )
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    if request.data.get("save", True):
        _remember(request.user, company=name, company_summary=out.summary, industry=out.industry)
    return Response(
        {"name": name, "summary": out.summary, "industry": out.industry, "sources": r.get("sources", [])[:4]}
    )


@api_view(["POST"])
def role_summary(request):
    from llm.prompts.paths import ROLE_SUMMARY_SYSTEM, RoleSummary
    from llm.structured import complete_json_sync

    role = str(request.data.get("role") or "").strip()[:120]
    if len(role) < 2:
        return Response({"code": "role_required"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, "profile_ai", 20):
        return denied
    try:
        out = complete_json_sync("utility", ROLE_SUMMARY_SYSTEM, f"Role: {role}", RoleSummary, max_tokens=800)
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    _remember(request.user, role_title=role, role_summary=out.summary)
    return Response(
        {"role": role, "summary": out.summary, "skills": out.skills, "matched": _skills_out(out.skills)}
    )


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@throttle_classes([CVThrottle])
def cv(request):
    """Upload a CV (PDF/DOCX/TXT) → current role, skills, summary. The file and its text are not stored."""
    from apps.docs.extract import ExtractError, extract, sniff
    from llm.prompts.paths import CV_SYSTEM, CVParsed
    from llm.structured import complete_json_sync

    f = request.FILES.get("file")
    if not f:
        return Response({"code": "file_required"}, status=status.HTTP_400_BAD_REQUEST)
    if f.size > CV_MAX_BYTES:
        return Response({"code": "file_too_large"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, "profile_ai", 20):  # before parsing: extraction itself costs CPU
        return denied
    data = f.read()
    try:
        text = "\n".join(t for _, t in extract(data, sniff(data, f.name)))[:20000]
    except ExtractError as e:
        return Response({"code": e.code}, status=status.HTTP_400_BAD_REQUEST)
    if len(text.strip()) < 40:
        return Response({"code": "no_text"}, status=status.HTTP_400_BAD_REQUEST)
    try:
        out = complete_json_sync(
            "utility", CV_SYSTEM, f"CV TEXT (data):\n<<<\n{text}\n>>>", CVParsed, max_tokens=1500
        )
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    _remember(
        request.user,
        role_title=out.current_role,
        cv_skills=", ".join(out.skills)[:300],
        cv_summary=out.summary,
    )
    return Response({**out.model_dump(), "matched": _skills_out(out.skills)})


@api_view(["POST"])
def target_role(request):
    """Free-text 'I want to become …' → required vs. have vs. missing skills, follow the gaps, suggested course goals."""
    from apps.study.about import about_of
    from llm.prompts.paths import TARGET_SYSTEM, TargetPlan
    from llm.structured import complete_json_sync

    role = str(request.data.get("role") or "").strip()[:120]
    if len(role) < 2:
        return Response({"code": "role_required"}, status=status.HTTP_400_BAD_REQUEST)
    if denied := _charge(request.user, "profile_ai", 20):
        return denied
    have = [
        us.skill.name
        for us in UserSkill.objects.filter(user=request.user, followed=True).select_related("skill")
    ]
    cv_sk = about_of(request.user).data.get("cv_skills", "")
    have_txt = ", ".join([*have, cv_sk]).strip(", ") or "none listed"
    try:
        out = complete_json_sync(
            "utility",
            TARGET_SYSTEM.format(role=role, have=have_txt[:600]),
            f"Target role: {role}",
            TargetPlan,
            max_tokens=1200,
        )
    except Exception:  # noqa: BLE001
        return Response({"code": "ai_unavailable"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    missing = _skills_out(out.missing)
    if request.data.get("follow", True):
        for i, s in enumerate(missing):
            us, _ = UserSkill.objects.get_or_create(
                user=request.user, skill_id=Skill.objects.get(slug=s["slug"]).id
            )
            if not us.followed or us.hidden:
                us.followed, us.hidden, us.order = True, False, us.order or 100 + i
                us.save()
    _remember(request.user, target_role=role)
    return Response(
        {
            "role": role,
            "required": out.required,
            "missing": out.missing,
            "missing_matched": missing,
            "courses": out.courses[:4],
        }
    )
