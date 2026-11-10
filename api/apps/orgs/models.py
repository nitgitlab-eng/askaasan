import secrets

from django.conf import settings
from django.db import models


def _code():
    # Short, unambiguous join code teachers can write on a board (no 0/O/1/I).
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(7))


def _token():
    return secrets.token_urlsafe(24)


class Organization(models.Model):
    class Kind(models.TextChoices):
        SCHOOL = "school"
        COLLEGE = "college"
        COACHING = "coaching"
        COMPANY = "company"

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=80, unique=True)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.SCHOOL)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Data Processing Agreement accepted for this school/company (DPDP Act: they are the data fiduciary for members).
    dpa_version = models.CharField(max_length=16, blank=True)
    career_slug = models.CharField(
        max_length=80, blank=True
    )  # target role framework for the competency heat-map
    dpa_accepted_at = models.DateTimeField(null=True, blank=True)
    dpa_accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # Milestone 5 — rebranding, custom member fields, per-org feature switches, setup wizard
    display_name = models.CharField(max_length=120, blank=True)  # shown to learners instead of `name`
    brand_color = models.CharField(max_length=7, blank=True)  # #rrggbb
    logo_url = models.CharField(max_length=300, blank=True)  # our own media URL only
    member_fields = models.JSONField(default=list, blank=True)  # [{key, label, type: text|select, options?}]
    features = models.JSONField(default=dict, blank=True)  # {mentor, live, roleplay, leaderboard, shop: bool}
    setup = models.JSONField(default=dict, blank=True)  # wizard steps the admin marked done/skipped
    # Milestone 9 — school structure: "About the organisation" (grounds AI generation) and target roles
    description = models.TextField(blank=True, max_length=1000)
    target_roles = models.JSONField(default=list, blank=True)  # CareerPath slugs
    # Institution workshops: distinct learners per calendar month across the org's workshop runs (set by the
    # platform admin together with the `workshops` feature).
    workshop_seats = models.PositiveIntegerField(default=0)
    # Set by a platform admin (unpaid, abuse, contract ended): members can't use the organisation's pages until lifted.
    suspended_at = models.DateTimeField(null=True, blank=True)
    suspended_reason = models.CharField(max_length=200, blank=True)


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner"
        ADMIN = "admin"
        MANAGER = "manager"  # teacher / team lead
        LEARNER = "learner"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.LEARNER)
    joined_at = models.DateTimeField(auto_now_add=True)
    fields = models.JSONField(
        default=dict, blank=True
    )  # custom member fields: {"roll_no": "12", "section": "B"}
    seat = models.BooleanField(default=False)  # holds one of the org's paid seats
    # Milestone 9: a unit admin is a manager limited to their units (explicit, never inferred from UnitAdmin rows);
    # prior_role is what they go back to when their last unit is removed. Partners joined only through a cohort.
    unit_scoped = models.BooleanField(default=False)
    prior_role = models.CharField(max_length=10, blank=True)
    partner = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["org", "user"], name="uniq_membership")]


class Group(models.Model):
    """A class / batch / team inside an organization, joined with a short code."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="groups")
    name = models.CharField(max_length=80)
    join_code = models.CharField(max_length=10, unique=True, default=_code)
    members = models.ManyToManyField(Membership, related_name="groups", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    unit = models.ForeignKey(
        "SubUnit", null=True, blank=True, on_delete=models.SET_NULL, related_name="groups"
    )  # sub-school / department


class Invitation(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(max_length=10, choices=Membership.Role.choices, default=Membership.Role.LEARNER)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)
    token = models.CharField(max_length=64, unique=True, default=_token)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    # Milestone 9: invite as a unit-scoped admin, or straight into a partner cohort
    unit = models.ForeignKey(
        "SubUnit", null=True, blank=True, on_delete=models.CASCADE, related_name="invitations"
    )
    cohort = models.ForeignKey(
        "Cohort", null=True, blank=True, on_delete=models.CASCADE, related_name="invitations"
    )  # cohort gone → invite gone


class Assignment(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="assignments")
    group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.CASCADE, related_name="assignments"
    )  # null = whole org
    # Exactly one of curriculum / scenario is set (a course or a role-play practice).
    curriculum = models.ForeignKey(
        "learning.Curriculum", null=True, blank=True, on_delete=models.CASCADE, related_name="assignments"
    )
    scenario = models.ForeignKey(
        "roleplay.Scenario", null=True, blank=True, on_delete=models.CASCADE, related_name="assignments"
    )
    mandatory = models.BooleanField(default=False)
    survey = models.ForeignKey(
        "Survey", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # end-of-training feedback
    note = models.CharField(max_length=300, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def kind(self) -> str:
        return "scenario" if self.scenario_id else "course"


class TeachInsight(models.Model):
    """Cached, paid AI read-outs for teachers: role-play class insights or per-lesson misconceptions."""

    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE, related_name="insights")
    kind = models.CharField(max_length=16)  # roleplay | misconceptions
    subsection = models.ForeignKey(
        "learning.Subsection", null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    scope = models.CharField(
        max_length=80, default="all"
    )  # which learners it was computed over (teacher's classes)
    data = models.JSONField(default=dict)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)


class Survey(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft"
        OPEN = "open"
        CLOSED = "closed"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="surveys")
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)  # null = whole org
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=500, blank=True)
    questions = models.JSONField(default=list)  # [{id, type, text, required, options?, rows?, min?, max?}]
    anonymous = models.BooleanField(default=True)
    public = models.BooleanField(default=False)  # anyone with the link can answer (no login)
    public_token = models.CharField(max_length=32, unique=True, default=_token)
    draw = models.JSONField(
        default=dict, blank=True
    )  # {"bank": id, "n": 3}: each respondent also gets n random bank questions
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    # Surveys v3: knowledge-test mode (scored questions, pass mark, review) and retakes
    kind = models.CharField(max_length=8, default="survey")  # survey | test
    pass_mark = models.PositiveSmallIntegerField(default=60)  # % needed to pass (tests)
    show_review = models.BooleanField(default=False)  # reveal correct answers after submit
    max_attempts = models.PositiveSmallIntegerField(default=1)  # 0 = unlimited
    cooldown_minutes = models.PositiveIntegerField(default=0)  # wait between attempts

    class Meta:
        ordering = ["-created_at"]


class SurveyResponse(models.Model):
    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="responses")
    # Anonymous surveys store only a keyed hash (prevents double-voting without linking to the person).
    respondent_key = models.CharField(max_length=64)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    answers = models.JSONField()
    submitted_at = models.DateTimeField(auto_now_add=True)
    attempt = models.PositiveSmallIntegerField(default=1)  # 1, 2, … when the survey allows retakes
    score = models.FloatField(null=True, blank=True)  # tests: points earned
    max_score = models.FloatField(null=True, blank=True)
    passed = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["survey", "respondent_key", "attempt"], name="uniq_survey_response_attempt"
            )
        ]


class QuestionBank(models.Model):
    """Reusable question pool for an org's surveys (draw N at random per respondent)."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="question_banks")
    name = models.CharField(max_length=120)
    questions = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)


class SurveyDraft(models.Model):
    """Save-and-resume: partial answers (and the drawn questions) until the respondent submits."""

    survey = models.ForeignKey(Survey, on_delete=models.CASCADE, related_name="drafts")
    respondent_key = models.CharField(max_length=64)
    asked = models.JSONField(
        default=list
    )  # question ids drawn for this respondent (bank questions are stored inline)
    extra = models.JSONField(default=list)  # the bank questions this respondent was given
    answers = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["survey", "respondent_key"], name="uniq_survey_draft")]


class Campaign(models.Model):
    """Guest invitation campaign: one shareable link with a quota and an expiry (plus optional emailed invites)."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="campaigns")
    name = models.CharField(max_length=120)
    group = models.ForeignKey(Group, null=True, blank=True, on_delete=models.SET_NULL)
    token = models.CharField(max_length=40, unique=True, default=_token)
    quota = models.PositiveIntegerField(default=50)
    used = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class ReferralCode(models.Model):
    """Org referral programme: people join with a code; each join is a ledger row the org can approve and mark paid."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="referral_codes")
    code = models.CharField(max_length=24, unique=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )  # who refers
    reward = models.CharField(max_length=160, blank=True)  # e.g. "₹100 per student who joins"
    reward_paise = models.PositiveIntegerField(default=0)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ReferralUse(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        PAID = "paid"
        REJECTED = "rejected"

    code = models.ForeignKey(ReferralCode, on_delete=models.CASCADE, related_name="uses")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    amount_paise = models.PositiveIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["code", "user"], name="uniq_referral_use")]


class OrgDocument(models.Model):
    """A manager's notes shared with the whole org (learners can read and ask Aasan about them), or a company
    knowledge-base upload (source="kb") that is read in the background: queued → reading → ready / failed."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        READING = "reading"
        READY = "ready"
        FAILED = "failed"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="documents")
    document = models.ForeignKey(
        "docs.Document", null=True, blank=True, on_delete=models.CASCADE, related_name="shared_in"
    )  # set once ready
    shared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=8, default="shared")  # shared | kb
    title = models.CharField(max_length=200, blank=True)
    filename = models.CharField(max_length=200, blank=True)
    kind = models.CharField(max_length=8, blank=True)  # pdf | docx | txt | md (sniffed from magic bytes)
    size = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.READY)
    error = models.CharField(max_length=40, blank=True)
    raw = models.BinaryField(null=True, blank=True)  # staged upload; cleared as soon as it has been read
    topics = models.JSONField(default=list, blank=True)  # key topics, extracted by AI once and cached
    topics_done = models.BooleanField(default=False)
    learners_can_read = models.BooleanField(
        default=False
    )  # KB: staff-only until an admin opts a document in (partners never)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["org", "document"], name="uniq_org_document")]


class SubUnit(models.Model):
    """A sub-school / department ("Primary", "Engineering") with its own target roles, course coverage and admins."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="units")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True)
    target_roles = models.JSONField(default=list, blank=True)  # CareerPath slugs
    courses = models.ManyToManyField(
        "learning.Curriculum", blank=True, related_name="in_units"
    )  # module coverage
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class UnitAdmin(models.Model):
    """A manager scoped to one unit (and its child units): they manage only that unit's groups, learners, assignments."""

    unit = models.ForeignKey(SubUnit, on_delete=models.CASCADE, related_name="admins")
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="unit_roles")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["unit", "membership"], name="uniq_unit_admin")]


class OrgSetupChat(models.Model):
    """'Set up with Kili': admin conversation; assistant turns carry proposals the admin accepts/rejects one by one."""

    org = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="setup_chat")
    messages = models.JSONField(default=list)  # [{role, content, proposals?, applied?, rejected?, errors?}]
    updated_at = models.DateTimeField(auto_now=True)


class Cohort(models.Model):
    """Partner programme: a set of courses granted to a cohort for an access window (progress is kept after it ends)."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="cohorts")
    name = models.CharField(max_length=120)
    partner = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=500, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    courses = models.ManyToManyField("learning.Curriculum", blank=True, related_name="cohorts")
    members = models.ManyToManyField(Membership, blank=True, related_name="cohorts")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_at"]


class TrainingRecord(models.Model):
    """Compliance training record: one row per learner per finished item an organisation gave them (course,
    role-play, workshop, knowledge test). Append-only evidence for audits — names, titles and the organisation are
    snapshots taken at completion, so later renames or deletions don't rewrite history. save() refuses updates; the
    only changes ever made are attach_certificate (fills the certificate once) and anonymise (account deletion)."""

    class Kind(models.TextChoices):
        COURSE = "course"
        SCENARIO = "scenario"
        WORKSHOP = "workshop"
        TEST = "test"

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="training_records")
    org_name = models.CharField(max_length=120)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    learner_name = models.CharField(max_length=120)
    learner_email = models.CharField(max_length=254, blank=True)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    title = models.CharField(max_length=200)
    assignment = models.ForeignKey(
        Assignment, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    curriculum = models.ForeignKey(
        "learning.Curriculum", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    scenario = models.ForeignKey(
        "roleplay.Scenario", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    workshop_run = models.ForeignKey(
        "workshops.WorkshopRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    survey = models.ForeignKey(Survey, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    assigned_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField()
    score = models.FloatField(null=True, blank=True)  # 0..1
    minutes = models.PositiveIntegerField(null=True, blank=True)  # estimated
    certificate = models.ForeignKey(
        "credentials.Certificate", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    certificate_code = models.CharField(max_length=40, blank=True)
    verify_url = models.CharField(max_length=300, blank=True)
    dedupe = models.CharField(max_length=80, unique=True)  # org:user:kind:item
    backfilled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-completed_at", "-id"]
        indexes = [models.Index(fields=["org", "completed_at"], name="orgs_trainrec_org_done")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("training records are append-only")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("training records are append-only")

    @classmethod
    def attach_certificate(cls, pk: int, cert) -> bool:
        """Fill the certificate once (never replaced)."""
        from apps.credentials.services import verify_url

        return bool(
            cls.objects.filter(pk=pk, certificate__isnull=True, certificate_code="").update(
                certificate=cert, certificate_code=cert.code, verify_url=verify_url(cert)
            )
        )

    @classmethod
    def anonymise(cls, user) -> int:
        """Account deletion: the organisation keeps the fact of the training, not the person."""
        return cls.objects.filter(user=user).update(
            user=None, learner_name="Deleted learner", learner_email=""
        )


def _domain_token():
    return secrets.token_hex(16)


class OrgDomain(models.Model):
    """An email domain an organisation proves it owns with a DNS TXT record (aasan-verify=<token>). Verified domains
    are what SSO accepts and enforces. Only one organisation can hold a domain verified at a time."""

    org = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(max_length=253)  # lower-case ASCII (IDNA)
    token = models.CharField(max_length=40, default=_domain_token)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    failing_since = models.DateTimeField(
        null=True, blank=True
    )  # daily re-check has not found the record since
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["domain"]
        constraints = [
            models.UniqueConstraint(fields=["org", "domain"], name="uniq_org_domain"),
            models.UniqueConstraint(
                fields=["domain"], condition=models.Q(verified_at__isnull=False), name="uniq_verified_domain"
            ),
        ]


class OrgSsoConfig(models.Model):
    """Enterprise SSO for one organisation: OpenID Connect with Google Workspace or Microsoft Entra ID (a single tenant).
    Issuer and endpoint URLs are fixed per provider in sso.py; the organisation supplies only its client ID/secret
    (and the Entra tenant ID)."""

    class Provider(models.TextChoices):
        GOOGLE = "google"
        MICROSOFT = "microsoft"

    org = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name="sso")
    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.GOOGLE)
    client_id = models.CharField(max_length=200, blank=True)
    client_secret_enc = models.TextField(blank=True)  # providers.crypto; never returned
    tenant_id = models.CharField(max_length=36, blank=True)  # Microsoft: the directory (tenant) UUID
    hosted_domains = models.JSONField(default=list, blank=True)  # ⊆ the org's verified domains
    default_role = models.CharField(max_length=10, default="learner")  # learner | manager
    default_group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    enabled = models.BooleanField(default=False)
    enforced = models.BooleanField(
        default=False
    )  # password sign-in refused for these domains (owners excepted)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)
