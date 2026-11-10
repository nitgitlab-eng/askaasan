"""Which courses an org staff member may put in front of learners (assign, cohort, unit coverage).

Never someone else's private draft or unlisted course: see assignable_q. Only the caller's own course may be published as a side effect of assigning it."""

from django.db.models import Count, Q
from django.utils import timezone

from apps.learning.models import Curriculum, Subsection


def author_shared_ids(org):
    """Courses whose own author assigned them in this org (an admin re-assigning someone else's course doesn't count)."""
    from django.db.models import F

    from .models import Assignment

    return Assignment.objects.filter(
        org=org, curriculum__isnull=False, created_by_id=F("curriculum__owner_id")
    ).values("curriculum_id")


def assignable_q(org, user) -> Q:
    """The one rule for units, cohorts, org assignments and teach: the caller's own courses, this org's published
    templates, catalog-approved courses, and courses their author already assigned in this org. A link-shared course
    elsewhere on the platform is NOT assignable by id (that would bypass its share token)."""
    published = Q(published_at__isnull=False)
    return Q(kind="authored") & (
        Q(owner=user)
        | (published & Q(template_scope="org", template_org=org))
        | (published & Q(catalog_status="approved"))
        | (published & Q(id__in=author_shared_ids(org)))
    )


def assignable_courses(org, user):
    return Curriculum.objects.filter(assignable_q(org, user)).distinct()


def ensure_published(cur, user, *, share_link: bool = True) -> str:
    """ "" when learners can open `cur`; otherwise publish it if the caller owns it and its lessons are ready.
    Returns an error code: not_published (someone else's unpublished course) or lessons_not_ready."""
    if cur.published_at:
        return ""
    if cur.owner_id != user.id:
        return "not_published"
    subs = Subsection.objects.filter(section__curriculum=cur).annotate(n=Count("activities"))
    if not subs.exists() or any(b.lesson_status != "ready" or b.n == 0 for b in subs):
        return "lessons_not_ready"
    fields = ["published_at", "updated_at"]
    cur.published_at = timezone.now()
    if (
        share_link
    ):  # an assignment shares it with the class by link; cohorts keep it private (window-limited access)
        cur.visibility = "link"
        fields.append("visibility")
    cur.save(update_fields=fields)
    return ""
