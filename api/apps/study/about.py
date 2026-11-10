"""Progressive profile: one short question at a time (end of lesson), used to personalise later lessons."""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import AboutMe

QUESTIONS = [  # asked in this order; "choices" = one tap, otherwise a short text answer
    {"key": "role", "choices": ["student", "working", "teacher", "job_seeker", "business", "other"]},
    {"key": "goals", "choices": ["exam", "job", "work", "curiosity", "teach"]},
    {"key": "style", "choices": ["examples", "practice", "stories", "visuals", "short"]},
    {"key": "tools", "choices": []},  # free text: tools/apps they use
]
KEYS = {q["key"] for q in QUESTIONS} | {
    "company",
    "company_summary",
    "industry",
    "role_title",
    "role_summary",
    "cv_skills",
    "cv_summary",
    "target_role",
}


def about_of(user) -> AboutMe:
    return AboutMe.objects.get_or_create(user=user)[0]


def next_question(a: AboutMe):
    return next((q for q in QUESTIONS if q["key"] not in a.data and q["key"] not in a.skipped), None)


def context_line(user) -> str:
    """Short learner context for lesson generation (empty when we know nothing)."""
    a = AboutMe.objects.filter(user=user).first()
    if not a or not a.data:
        return ""
    d = a.data
    bits = [
        f"{k.replace('_', ' ')}: {str(d[k])[:200]}"
        for k in (
            "role",
            "role_title",
            "company",
            "industry",
            "target_role",
            "goals",
            "style",
            "tools",
            "cv_skills",
        )
        if d.get(k)
    ]
    return (
        "About the learner (personalise examples to this, never mention it explicitly): "
        + "; ".join(bits)
        + "."
    )


@api_view(["GET", "POST"])
def about(request):
    a = about_of(request.user)
    if request.method == "POST":
        if skip := request.data.get("skip"):
            if skip in KEYS and skip not in a.skipped:
                a.skipped = [*a.skipped, skip][:20]
        else:
            key, value = request.data.get("key"), request.data.get("value")
            if key not in KEYS or not isinstance(value, (str, list)):
                return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
            q = next((q for q in QUESTIONS if q["key"] == key), None)
            if q and q["choices"]:
                vals = value if isinstance(value, list) else [value]
                if not vals or not set(vals) <= set(q["choices"]):
                    return Response({"code": "bad_answer"}, status=status.HTTP_400_BAD_REQUEST)
                value = vals if isinstance(value, list) else vals[0]
            else:
                value = (", ".join(map(str, value)) if isinstance(value, list) else value).strip()[:300]
            a.data = {**a.data, key: value}
        a.save()
    return Response({"data": a.data, "next": next_question(a)})
