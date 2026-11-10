"""Optional (non-transactional) email: respects notification preferences and always carries a one-click unsubscribe.

Transactional mail (verification, password reset, receipts, invites, account deletion, guardian notice) is sent
directly and is not affected by these preferences."""

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail

from .preferences import upgrade

CATEGORIES = {"email_study", "email_plan", "email_workshops", "email_winback"}
SALT = "aasan-unsubscribe"


def wants(user, category: str) -> bool:
    return bool(upgrade(user.preferences.data)["notifications"].get(category, True))


def unsubscribe_url(user, category: str) -> str:
    token = signing.dumps({"u": user.id, "c": category}, salt=SALT)
    return f"{settings.FRONTEND_URL}/unsubscribe?t={token}"


def send_optional(user, category: str, subject: str, body: str, html: str = "") -> bool:
    if category not in CATEGORIES or not wants(user, category):
        return False
    url = unsubscribe_url(user, category)
    footer = f"\n\n—\nDon't want these emails? Unsubscribe in one click: {url}\nOr change it any time in Aasan → Account & privacy."
    html_msg = None
    if html:
        from django.utils.html import escape

        html_msg = (
            f'{html}<p style="color:#7a6656;font-size:12px;margin-top:24px">Don\'t want these emails? '
            f'<a href="{escape(url)}">Unsubscribe in one click</a>.</p>'
        )
    send_mail(subject, body + footer, None, [user.email], fail_silently=True, html_message=html_msg)
    return True


def unsubscribe(token: str) -> tuple[bool, str]:
    from django.contrib.auth import get_user_model

    try:
        data = signing.loads(token, salt=SALT, max_age=60 * 60 * 24 * 365)
    except signing.BadSignature:
        return False, ""
    user = get_user_model().objects.filter(pk=data.get("u")).first()
    cat = data.get("c")
    if not user or cat not in CATEGORIES:
        return False, ""
    prefs = user.preferences
    d = upgrade(prefs.data)
    d["notifications"][cat] = False
    prefs.data = d
    prefs.save(update_fields=["data", "updated_at"])
    return True, cat
