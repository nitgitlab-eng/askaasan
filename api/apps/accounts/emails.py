import hashlib
import secrets
from datetime import timedelta
from html import escape

from django.conf import settings
from django.core.mail import send_mail

from . import counters
from .models import OneTimeToken

RESET_TTL = timedelta(hours=1)  # a reset link is a password in an inbox: keep its life short
RESET_OTP_TTL = timedelta(minutes=15)  # 6 digits are guessable, so the code lives shorter than the link
RESET_OTP_TRIES = 5


def reset_otp_key(user) -> str:
    return f"reset-otp:{user.id}"


def send_verification(user):
    tok = OneTimeToken.issue(user, OneTimeToken.Purpose.VERIFY_EMAIL)
    link = f"{settings.FRONTEND_URL}/verify-email?token={tok.token}"
    send_mail(
        "Aasan — உங்கள் மின்னஞ்சலை உறுதிப்படுத்துங்கள் / Verify your email",
        f"வணக்கம்! Verify your email: {link}",
        None,
        [user.email],
    )


def _reset_html(otp: str, link: str) -> str:
    digits = "".join(
        f'<span style="display:inline-block;width:40px;margin:0 3px;padding:10px 0;border-radius:10px;'
        f'background:#f1f5f9;font-size:26px;font-weight:700;color:#0f172a">{d}</span>'
        for d in otp
    )
    return f"""<!doctype html>
<html><body style="margin:0;padding:24px;background:#f8fafc;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
    <table role="presentation" width="100%" style="max-width:480px;background:#ffffff;border-radius:16px;padding:32px">
      <tr><td>
        <h1 style="margin:0 0 4px;font-size:22px;color:#0f766e">Aasan · ஆசான்</h1>
        <p style="margin:0 0 20px;color:#475569">கடவுச்சொல் மீட்டமைப்பு / Reset your password</p>
        <p style="margin:0 0 12px">Enter this code on the reset page. உங்கள் குறியீடு:</p>
        <p style="margin:0 0 12px;text-align:center">{digits}</p>
        <p style="margin:0 0 24px;color:#475569;font-size:14px">The code expires in 15 minutes.
          இந்தக் குறியீடு 15 நிமிடங்களில் காலாவதியாகும்.</p>
        <p style="margin:0 0 24px;font-size:14px">Or reset with this link (valid 1 hour):<br>
          <a href="{escape(link)}" style="color:#0f766e">{escape(link)}</a></p>
        <p style="margin:0;color:#94a3b8;font-size:12px">Didn't ask to reset your password? Ignore this email —
          your password stays the same. Never share this code with anyone.</p>
      </td></tr>
    </table>
  </td></tr></table>
</body></html>"""


def send_password_reset(user):
    """Email a 6-digit code (entered on /forgot-password) and a one-time link (/reset-password); either one works."""
    tok = OneTimeToken.issue(user, OneTimeToken.Purpose.RESET_PASSWORD, ttl=RESET_TTL)
    link = f"{settings.FRONTEND_URL}/reset-password?token={tok.token}"
    otp = f"{secrets.randbelow(10**6):06d}"
    key = reset_otp_key(user)
    ttl = int(RESET_OTP_TTL.total_seconds())
    # Only a hash is kept, in the never-evicting security store; a new mail replaces the old code and its tries.
    counters.store().set(key, {"h": hashlib.sha256(otp.encode()).hexdigest()}, ttl)
    counters.clear(f"{key}:tries")
    send_mail(
        "Aasan — கடவுச்சொல் மீட்டமைப்பு / Reset your password",
        (
            f"Your password reset code is {otp}. It expires in 15 minutes.\n\n"
            f"Or reset with this link: {link}\nThis link expires in 1 hour.\n\n"
            "Didn't ask for this? Ignore this email. Never share this code with anyone."
        ),
        None,
        [user.email],
        html_message=_reset_html(otp, link),
    )


def check_reset_otp(user, code: str) -> str | None:
    """→ None when `code` is the user's current reset code (it is used up), else "wrong_code" / "otp_locked".
    5 wrong tries throw the code away, so it can't be guessed across many requests."""
    key = reset_otp_key(user)
    held = counters.store().get(key)
    if not held:
        return "wrong_code"
    if counters.bump(f"{key}:tries", int(RESET_OTP_TTL.total_seconds())) > RESET_OTP_TRIES:
        counters.clear(key)
        counters.clear(f"{key}:tries")
        return "otp_locked"
    if not secrets.compare_digest(held["h"], hashlib.sha256(code.strip().encode()).hexdigest()):
        return "wrong_code"
    counters.clear(key)
    counters.clear(f"{key}:tries")
    return None
