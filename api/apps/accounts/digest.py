"""B4: the daily nudge digest — one short email with one-tap deep links (WhatsApp-style, no new vendor).

Sent at the learner's reminder time on study days (replaces the plain reminder). Every item links straight to the
screen that does it."""

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from django.utils.html import escape

log = logging.getLogger(__name__)

TXT = {
    "en": {
        "subject": "{name}: your {n}-minute plan for today 📚",
        "hi": "Here's today, in one tap each:",
        "streak": "🔥 {n}-day streak — keep it alive today",
        "streak_new": "🔥 Start a streak today",
        "reviews": "🔁 {n} review cards are due",
        "today": "✅ Today's revision: {n} quick stations",
        "continue": "▶️ Continue “{title}”",
        "block": "🗓️ Planned at {time}: {title}",
        "rec": "✨ For you: {title}",
        "start": "📘 Start a lesson",
        "bye": "See you soon! — {name}",
    },
    "ta": {
        "subject": "{name}: இன்றைய {n} நிமிடத் திட்டம் 📚",
        "hi": "இன்று செய்ய வேண்டியவை — ஒவ்வொன்றும் ஒரு தொடுதலில்:",
        "streak": "🔥 {n} நாள் தொடர் — இன்றும் தொடருங்கள்",
        "streak_new": "🔥 இன்று ஒரு தொடரைத் தொடங்குங்கள்",
        "reviews": "🔁 {n} மீள்பார்வை அட்டைகள் காத்திருக்கின்றன",
        "today": "✅ இன்றைய மீள்பார்வை: {n} சிறு நிலையங்கள்",
        "continue": "▶️ “{title}” ஐத் தொடருங்கள்",
        "block": "🗓️ {time} க்குத் திட்டமிட்டது: {title}",
        "rec": "✨ உங்களுக்காக: {title}",
        "start": "📘 ஒரு பாடத்தைத் தொடங்குங்கள்",
        "bye": "விரைவில் சந்திப்போம்! — {name}",
    },
}


def items(user, lang: str) -> list[tuple[str, str]]:
    """[(line, path)] — only things that apply right now."""
    from apps.game.services import stats_for
    from apps.learning.models import UserSubsectionState
    from apps.review.models import ReviewCard

    T = TXT[lang]
    out = []
    s = stats_for(user)
    today = timezone.localdate()
    if s.streak and s.last_active == today - timedelta(days=1):
        out.append((T["streak"].format(n=s.streak), "/today"))
    elif not s.streak or (s.last_active and s.last_active < today - timedelta(days=1)):
        out.append((T["streak_new"], "/today"))
    due = ReviewCard.objects.filter(user=user, due__lte=timezone.now()).count()
    if due:
        out.append((T["reviews"].format(n=due), "/review"))
    try:
        from apps.study.today import _state

        dr = _state(user)
        left = [st for st in dr.stations if st["key"] not in dr.done]
        if left:
            out.append((T["today"].format(n=len(left)), "/today"))
    except Exception:  # a digest item failing must not stop the email
        log.warning("digest: today stations failed for %s", user.id, exc_info=True)
    st = (
        UserSubsectionState.objects.filter(user=user, status="in_progress")
        .select_related("subsection__section")
        .order_by("-started_at")
        .first()
    )
    if st:
        sub = st.subsection
        out.append(
            (
                T["continue"].format(title=sub.title[:80]),
                f"/learn/{sub.section.curriculum_id}/lesson/{sub.id}",
            )
        )
    from apps.study.models import StudyBlock

    blk = (
        StudyBlock.objects.filter(user=user, date=today, status="planned")
        .exclude(kind="today")
        .order_by("start")
        .first()
    )
    if blk and blk.title:
        out.append((T["block"].format(time=blk.start, title=blk.title[:60]), blk.link or "/plan"))
    try:
        from apps.paths.services import recommend

        rec = next(
            (
                r
                for r in recommend(user, limit=6)
                if r["kind"] in ("next", "start", "path", "practice") and r["link"] not in {p for _, p in out}
            ),
            None,
        )
        if rec:
            out.append((T["rec"].format(title=rec["title"][:80]), rec["link"]))
    except Exception:
        log.warning("digest: recommendation failed for %s", user.id, exc_info=True)
    if not any(p.startswith("/learn") for _, p in out):
        out.append((T["start"], "/learn"))
    return out[:6]


def render(lines: list[tuple[str, str]], hi: str, bye: str) -> tuple[str, str]:
    """The digest card: a greeting, one tappable row per (line, in-app path), a sign-off. → (text, html).
    Shared with the win-back emails (winback.py)."""
    base = settings.FRONTEND_URL.rstrip("/")
    text = hi + "\n\n" + "\n".join(f"{line}\n   {base}{path}" for line, path in lines) + "\n\n" + bye
    rows = "".join(
        f'<a href="{escape(base + path)}" style="display:block;margin:8px 0;padding:12px 14px;border:2px solid #f1dcc6;border-radius:14px;'
        f'color:#2a1d12;text-decoration:none;font-size:16px">{escape(line)} <span style="color:#f97316">→</span></a>'
        for line, path in lines
    )
    html = (
        f'<div style="font-family:system-ui,sans-serif;max-width:520px;margin:auto;background:#fff8f0;padding:20px;border-radius:18px">'
        f'<p style="font-size:16px;color:#2a1d12">{escape(hi)}</p>{rows}<p style="color:#7a6656">{escape(bye)}</p></div>'
    )
    return text, html


def build(user, prefs) -> tuple[str, str, str]:
    lang = "ta" if user.profile.language == "ta" else "en"
    T = TXT[lang]
    name = prefs["mascot"]["name"]
    subject = T["subject"].format(name=name, n=prefs["learning"]["daily_goal_minutes"])
    text, html = render(items(user, lang), T["hi"], T["bye"].format(name=name))
    return subject, text, html
