"""Guest campaigns: per prospect an AI-tailored demo lesson (built with the normal lesson/activity builders, so answer
keys stay on the server), a guest link + QR for it, and a drafted plain-text outreach email the manager sends."""

import csv
import io
import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.core.signing import dumps
from django.core.validators import validate_email
from django.db import transaction
from django.forms import ValidationError
from django.utils import timezone

from apps.learning import activities
from apps.learning.models import Activity, Curriculum, Section, Subsection
from apps.learning.services import _valid
from apps.legal.mail import EMAIL_NOT_CONFIGURED, mail_ready
from llm.base import LLMError
from llm.prompts.curriculum import LANG_RULE, to_typed
from llm.prompts.guests import DEMO_TYPES, DemoPackage, demo_prompts
from llm.structured import complete_json_sync

from .models import GuestLink, GuestOptOut, Prospect
from .services import UNSUB_SALT, limit, public_url

log = logging.getLogger(__name__)
MAX_PROSPECTS = 25
# Fixed by us: org-chosen text never goes into a subject line (spoofing / phishing guard).
SEND_SUBJECT = "A short interactive demo lesson for your team"


def org_name(org) -> str:
    return (org.display_name or org.name)[:120]


def parse_prospects(text: str) -> tuple[list[dict], list[str]]:
    """Pasted lines or CSV: company, email[, industry]. A header row is skipped. → (rows, errors)."""
    rows, errors, seen = [], [], set()
    for i, rec in enumerate(csv.reader(io.StringIO(text[:100_000])), 1):
        cells = [c.strip() for c in rec]
        if not any(cells):
            continue
        if i == 1 and len(cells) >= 2 and cells[1].lower() in ("email", "e-mail", "contact email", "contact"):
            continue
        if len(cells) < 2:
            errors.append(f"line {i}: need company and email")
            continue
        company, email, industry = (
            cells[0][:160],
            cells[1].lower()[:254],
            (cells[2] if len(cells) > 2 else "")[:120],
        )
        try:
            validate_email(email)
        except ValidationError:
            errors.append(f"line {i}: invalid email")
            continue
        if not company:
            errors.append(f"line {i}: company missing")
            continue
        if email in seen:
            continue
        seen.add(email)
        rows.append({"company": company, "email": email, "industry": industry})
    return rows, errors


def build_prospect(prospect_id: int) -> None:
    """Background job: AI demo lesson → authored course (published as link-only) → guest link → email draft."""
    p = Prospect.objects.select_related("campaign__org", "campaign__created_by").get(pk=prospect_id)
    camp = p.campaign
    owner = camp.created_by
    if owner is None:
        Prospect.objects.filter(pk=p.pk).update(status=Prospect.Status.FAILED, error="no_owner")
        return
    system, user = demo_prompts(
        camp.topic, p.company, p.industry, org_name(camp.org), LANG_RULE.get(camp.language, LANG_RULE["en"])
    )
    try:
        pkg = complete_json_sync("author", system, user, DemoPackage, max_tokens=6000, effort="medium")
    except Exception as e:  # noqa: BLE001 — a failed prospect must not kill the batch
        code = e.code if isinstance(e, LLMError) else "internal_error"
        log.warning("guest demo generation failed for prospect %s: %s", prospect_id, code)
        Prospect.objects.filter(pk=p.pk).update(status=Prospect.Status.FAILED, error=code[:120])
        return
    acts = [t for t in (to_typed(f) for f in pkg.activities if f.type in DEMO_TYPES) if t and _valid(t)][:3]
    if len(acts) < 1:
        Prospect.objects.filter(pk=p.pk).update(status=Prospect.Status.FAILED, error="generation_invalid")
        return
    with transaction.atomic():
        old_course = p.course
        cur = Curriculum.objects.create(
            owner=owner,
            kind=Curriculum.Kind.AUTHORED,
            goal=f"Demo: {camp.topic}"[:300],
            title=pkg.course_title[:200],
            description=pkg.description[:2000],
            language=camp.language,
            status=Curriculum.Status.READY,
            visibility=Curriculum.Visibility.LINK,
            published_at=timezone.now(),
            cover_emoji="✨",
        )
        sec = Section.objects.create(curriculum=cur, order=0, title=pkg.course_title[:200])
        sub = Subsection.objects.create(
            section=sec,
            order=0,
            title=pkg.lesson_title[:200],
            objective=pkg.objective[:500],
            explanation_md=pkg.explanation_md,
            key_points=pkg.key_points[:5],
            lesson_status=Subsection.LessonStatus.READY,
        )
        for i, act in enumerate(acts):
            payload, key = activities.build(act, seed=sub.id * 100 + i)
            Activity.objects.create(
                subsection=sub,
                order=i,
                type=act["type"],
                title=act["title"][:200],
                payload=payload,
                key=key,
                source=act,
            )
        if p.link_id:  # regenerate: the same link (and QR) now points at the new lesson
            GuestLink.objects.filter(pk=p.link_id).update(
                course=cur, target_kind=GuestLink.Target.COURSE, updated_at=timezone.now()
            )
            link_id = p.link_id
        else:
            link_id = GuestLink.objects.create(
                owner=owner,
                org=camp.org,
                label=f"{p.company} demo"[:120],
                course=cur,
                max_uses=50,
                expires_at=timezone.now() + timedelta(days=60),
            ).id
        Prospect.objects.filter(pk=p.pk).update(
            status=Prospect.Status.READY,
            error="",
            course=cur,
            link_id=link_id,
            subject=" ".join(pkg.email_subject.split())[:160],
            body=pkg.email_body[:4000],
        )
        if (
            old_course
            and not old_course.guest_links.exclude(pk=link_id).exists()
            and not old_course.enrollments.exists()
        ):
            old_course.delete()  # the earlier draft lesson nobody else links to


def unsubscribe_url(email: str) -> str:
    from django.conf import settings

    return f"{settings.FRONTEND_URL.rstrip('/')}/api/guests/unsubscribe/?t={dumps({'e': email}, salt=UNSUB_SALT)}"


def compose(p: Prospect) -> tuple[str, str]:
    """Final plain-text email: the manager's body + link + who sent it + unsubscribe line."""
    body = (p.body or "").replace("\r", "").strip()
    footer = (
        f"\n\nTry the demo lesson (no sign-up needed): {public_url(p.link)}\n\n—\nSent via Aasan on behalf of "
        f"{org_name(p.campaign.org)}.\nDon't want emails like this? Unsubscribe: {unsubscribe_url(p.email)}"
    )
    return SEND_SUBJECT, body + footer


def sends_today(org) -> int:
    return Prospect.objects.filter(campaign__org=org, sent_at__date=timezone.localdate()).count()


def org_daily_limit(org) -> int:
    """New organisations (under 7 days) and those without an email-verified owner may send only a handful a day."""
    from apps.orgs.models import Membership

    cap = limit("GUEST_CAMPAIGN_SENDS_PER_DAY", 30)
    verified_owner = Membership.objects.filter(org=org, role="owner", user__email_verified=True).exists()
    if org.created_at > timezone.now() - timedelta(days=7) or not verified_owner:
        cap = min(cap, limit("GUEST_CAMPAIGN_NEW_ORG_PER_DAY", 5))
    return cap


def send(p: Prospect, sender) -> str:
    """Send one prospect email → "" on success or an error code. Caller holds the send lock + org row lock.
    Caps: per org per day, per sending account per day (across all its orgs), and platform-wide per day."""
    if p.status == Prospect.Status.SENT:
        return "already_sent"
    if p.status != Prospect.Status.READY or not p.link_id or not p.body.strip():
        return "not_ready"
    if GuestOptOut.objects.filter(email=p.email.lower()).exists():
        return "unsubscribed"
    today = timezone.localdate()
    if Prospect.objects.filter(sent_at__date=today).count() >= limit("GUEST_CAMPAIGN_GLOBAL_PER_DAY", 500):
        return "global_limit"
    if Prospect.objects.filter(sent_by=sender, sent_at__date=today).count() >= limit(
        "GUEST_CAMPAIGN_PER_ACCOUNT_DAY", 60
    ):
        return "account_limit"
    if sends_today(p.campaign.org) >= org_daily_limit(p.campaign.org):
        return "daily_limit"
    if not mail_ready():
        return EMAIL_NOT_CONFIGURED
    subject, body = compose(p)
    try:
        send_mail(subject, body, None, [p.email], fail_silently=False)
    except Exception:
        log.warning("guest campaign mail failed for prospect %s", p.id, exc_info=True)
        return "send_failed"
    Prospect.objects.filter(pk=p.pk).update(
        status=Prospect.Status.SENT, sent_at=timezone.now(), sent_by=sender
    )
    return ""
