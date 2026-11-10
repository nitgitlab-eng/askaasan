from django.conf import settings
from django.db import models


class Skill(models.Model):
    slug = models.SlugField(max_length=60, unique=True)
    name = models.CharField(max_length=80)
    name_ta = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=40)
    description = models.CharField(max_length=240, blank=True)
    keywords = models.JSONField(default=list, blank=True)  # used to match free-text course skills
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]


class UserSkill(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="skill_prefs")
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE, related_name="+")
    followed = models.BooleanField(default=False)
    hidden = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    self_rating = models.PositiveSmallIntegerField(default=0)  # 0 = not rated, 1..5
    assessed_level = models.PositiveSmallIntegerField(default=0)  # from a career assessment, 1..5
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "skill"], name="uniq_user_skill")]
        ordering = ["order", "id"]


class CuratedPath(models.Model):
    """An ordered learning path. Each step is a goal the learner turns into an AI course (or an existing catalog course)."""

    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=140)
    title_ta = models.CharField(max_length=200, blank=True)
    description = models.CharField(max_length=400, blank=True)
    emoji = models.CharField(max_length=8, default="🧭")
    level = models.CharField(max_length=16, default="beginner")
    steps = models.JSONField(default=list)  # [{"title", "goal", "skill"}]
    skills = models.ManyToManyField(Skill, blank=True, related_name="paths")
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="paths"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class PathEnrollment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="path_enrollments"
    )
    path = models.ForeignKey(CuratedPath, on_delete=models.CASCADE, related_name="enrollments")
    step_courses = models.JSONField(default=dict)  # {"<step index>": curriculum_id}
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "path"], name="uniq_path_enrollment")]


class CareerPath(models.Model):
    """A role with the competency levels it needs (1 aware … 5 expert) and a path to get there."""

    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=120)
    title_ta = models.CharField(max_length=200, blank=True)
    summary = models.CharField(max_length=400)
    salary_band = models.CharField(max_length=80, blank=True)  # indicative, India
    outlook = models.CharField(max_length=200, blank=True)
    emoji = models.CharField(max_length=8, default="💼")
    requirements = models.JSONField(default=list)  # [{"skill": slug, "level": 1..5}]
    path = models.ForeignKey(CuratedPath, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    org = models.ForeignKey(
        "orgs.Organization", null=True, blank=True, on_delete=models.CASCADE, related_name="careers"
    )
    published = models.BooleanField(default=True)
    # Role ladder: how senior this role is, the roles people usually move into next, and senior roles further up.
    seniority = models.CharField(max_length=8, default="entry")  # entry | mid | senior | lead
    next_roles = models.JSONField(default=list, blank=True)  # CareerPath slugs
    senior_roles = models.JSONField(default=list, blank=True)  # CareerPath slugs


class CareerPlan(models.Model):
    """'Plan my next 30 days' toward a role: 4 dated weeks of goals (each tied to a skill and a course/lesson or a new
    course goal) plus role types worth talking to. One per learner and role; regenerating replaces it."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="career_plans")
    career = models.ForeignKey(CareerPath, on_delete=models.CASCADE, related_name="plans")
    start_date = models.DateField()
    summary = models.CharField(max_length=400, blank=True)
    weeks = models.JSONField(default=list)  # [{week, theme, start, end}]
    goals = models.JSONField(
        default=list
    )  # [{id, week, order, title, skill, skill_name, due, course_id, lesson_id, course_title, lesson_title, course_goal, done}]
    people = models.JSONField(default=list)  # [{role, why, ask}]
    generations = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "career"], name="uniq_career_plan")]


class RoleAssessment(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="role_assessments"
    )
    career = models.ForeignKey(CareerPath, on_delete=models.CASCADE, related_name="assessments")
    questions = models.JSONField(default=list)  # server-side, includes answer keys
    levels = models.JSONField(default=dict)  # {skill: level} after submit
    score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class Placement(models.Model):
    """Onboarding placement test: a few graded questions that set the learner's starting level."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    goal = models.CharField(max_length=300)
    questions = models.JSONField(default=list)
    level = models.CharField(max_length=16, blank=True)
    score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
