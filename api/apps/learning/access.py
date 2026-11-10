"""Single source of truth for who may see/learn a course.

A course is viewable by its owner, and — once published — by learners who
enrolled via the share link or the approved catalog. Mutating authoring
endpoints use `owned_*` instead."""

from django.db.models import Q
from django.http import Http404
from django.utils import timezone

from .models import Activity, Curriculum, Section, Subsection


def viewable_q(user, prefix: str = "") -> Q:
    p = prefix
    now = timezone.now()
    # Partner-cohort enrollments only count inside their access window (progress is kept either way).
    in_window = (
        Q(**{f"{p}enrollments__access_from__isnull": True}) | Q(**{f"{p}enrollments__access_from__lte": now})
    ) & (
        Q(**{f"{p}enrollments__access_until__isnull": True}) | Q(**{f"{p}enrollments__access_until__gt": now})
    )
    return Q(**{f"{p}owner": user}) | (
        Q(**{f"{p}enrollments__user": user, f"{p}published_at__isnull": False}) & in_window
    )


def viewable_curricula(user):
    return Curriculum.objects.filter(viewable_q(user)).distinct()


def get_viewable_curriculum(user, pk) -> Curriculum:
    cur = viewable_curricula(user).filter(pk=pk).first()
    if not cur:
        raise Http404
    return cur


def get_viewable_section(user, pk) -> Section:
    s = (
        Section.objects.filter(viewable_q(user, "curriculum__"), pk=pk)
        .select_related("curriculum")
        .distinct()
        .first()
    )
    if not s:
        raise Http404
    return s


def get_viewable_subsection(user, pk) -> Subsection:
    s = (
        Subsection.objects.filter(viewable_q(user, "section__curriculum__"), pk=pk)
        .select_related("section__curriculum")
        .distinct()
        .first()
    )
    if not s or ((s.archived or s.section.archived) and s.section.curriculum.owner_id != user.id):
        raise Http404  # archived lessons are hidden from learners (the author can still preview)
    return s


def get_viewable_activity(user, pk) -> Activity:
    a = (
        # Fast-track questions are private to one learner's run (graded only via its own submit endpoint).
        Activity.objects.filter(viewable_q(user, "subsection__section__curriculum__"), pk=pk)
        .exclude(kind="fasttrack")
        .select_related("subsection__section__curriculum")
        .distinct()
        .first()
    )
    if not a or (
        (a.subsection.archived or a.subsection.section.archived)
        and a.subsection.section.curriculum.owner_id != user.id
    ):
        raise Http404
    return a


def is_owner(user, curriculum) -> bool:
    return curriculum.owner_id == user.id
