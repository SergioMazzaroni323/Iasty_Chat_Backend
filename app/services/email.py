import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PURPOSE_VERIFY_EMAIL = "verify_email"
PURPOSE_PASSWORD_RESET = "password_reset"


class EmailSendError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


_last_email_error: str | None = None


def get_last_email_error() -> str | None:
    return _last_email_error


def smtp_configured() -> bool:
    return bool(settings.smtp_user and settings.smtp_password)


def resend_configured() -> bool:
    return bool(settings.resend_api_key)


def email_configured() -> bool:
    provider = _resolve_provider()
    return provider in ("smtp", "resend", "gmail")


def get_email_provider() -> str:
    from app.services.gmail_api import gmail_configured

    provider = settings.email_provider.lower().strip()
    if provider == "gmail":
        return "gmail" if gmail_configured() else "none"
    if provider == "resend":
        return "resend" if resend_configured() else "none"
    if provider == "smtp":
        return "smtp" if smtp_configured() else "none"
    if gmail_configured():
        return "gmail"
    if resend_configured():
        return "resend"
    if smtp_configured():
        return "smtp"
    return "none"


def _resolve_provider() -> str:
    return get_email_provider()


def _build_message(to: str, subject: str, html: str, text: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    sender = settings.smtp_from or settings.smtp_user
    msg["From"] = f"{settings.smtp_from_name} <{sender}>"
    msg["To"] = to
    msg.attach(MIMEText(text or html, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


def _send_via_smtp(msg: MIMEMultipart, sender: str, to: str) -> None:
    if settings.smtp_use_ssl or settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(sender, [to], msg.as_string())
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.starttls()
        server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(sender, [to], msg.as_string())


def _send_via_resend(to: str, subject: str, html: str, text: str) -> None:
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        json={
            "from": settings.resend_from,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text or html,
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        try:
            payload = response.json()
            message = payload.get("message") or response.text.strip()
        except Exception:
            message = response.text.strip() or response.reason_phrase
        raise EmailSendError(message)


def send_email(to: str, subject: str, html: str, text: str = "") -> bool:
    global _last_email_error
    _last_email_error = None
    provider = _resolve_provider()
    if provider == "none":
        _last_email_error = "Email is not configured on the server."
        logger.warning("Email is not configured; skipped sending email to %s", to)
        return False

    try:
        if provider == "gmail":
            from app.services.gmail_api import send_via_gmail

            send_via_gmail(to, subject, html, text)
            return True

        if provider == "resend":
            _send_via_resend(to, subject, html, text)
            return True

        sender = settings.smtp_from or settings.smtp_user
        msg = _build_message(to, subject, html, text)
        _send_via_smtp(msg, sender, to)
        return True
    except EmailSendError as exc:
        _last_email_error = exc.message
        logger.error("Failed to send email to %s via %s: %s", to, provider, exc.message)
        return False
    except TimeoutError:
        _last_email_error = (
            "SMTP connection timed out. Your network is likely blocking outbound SMTP. "
            "Use EMAIL_PROVIDER=gmail or RESEND_API_KEY instead."
        )
        logger.error(
            "SMTP connection timed out to %s:%s. Your network is likely blocking outbound SMTP.",
            settings.smtp_host,
            settings.smtp_port,
        )
        return False
    except OSError as exc:
        _last_email_error = f"SMTP connection failed ({exc}). Use EMAIL_PROVIDER=gmail instead."
        logger.error(
            "SMTP connection failed to %s:%s (%s).",
            settings.smtp_host,
            settings.smtp_port,
            exc,
        )
        return False
    except Exception as exc:
        from app.services.gmail_api import GmailSendError

        if isinstance(exc, GmailSendError):
            _last_email_error = exc.message
            logger.error("Failed to send email to %s via %s: %s", to, provider, exc.message)
            return False
        _last_email_error = "Unexpected email delivery failure."
        logger.exception("Failed to send email to %s via %s", to, provider)
        return False


def _email_shell(title: str, body_html: str) -> str:
    return f"""<!DOCTYPE html>
<html>
  <body style="font-family:Arial,sans-serif;line-height:1.5;color:#111827;">
    <div style="max-width:560px;margin:0 auto;padding:24px;">
      <h2 style="margin:0 0 16px;">{title}</h2>
      {body_html}
      <p style="margin-top:24px;font-size:12px;color:#6b7280;">If you did not request this, you can ignore this email.</p>
    </div>
  </body>
</html>"""


def send_verification_email(to: str, token: str) -> bool:
    link = f"{settings.frontend_url.rstrip('/')}/verify-email?token={token}"
    html = _email_shell(
        "Verify your Iasty email",
        f"""<p>Thanks for signing up. Click the button below to verify your email address.</p>
      <p style="margin:24px 0;">
        <a href="{link}" style="background:#6366f1;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;display:inline-block;">
          Verify email
        </a>
      </p>
      <p style="font-size:13px;color:#6b7280;">Or copy this link:<br><span style="word-break:break-all;">{link}</span></p>""",
    )
    return send_email(to, "Verify your Iasty email", html, f"Verify your email: {link}")


def send_password_reset_email(to: str, token: str) -> bool:
    link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={token}"
    html = _email_shell(
        "Reset your Iasty password",
        f"""<p>We received a request to reset your password. Click the button below to choose a new one.</p>
      <p style="margin:24px 0;">
        <a href="{link}" style="background:#6366f1;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;display:inline-block;">
          Reset password
        </a>
      </p>
      <p style="font-size:13px;color:#6b7280;">This link expires in {settings.password_reset_expire_hours} hour(s).</p>
      <p style="font-size:13px;color:#6b7280;word-break:break-all;">{link}</p>""",
    )
    return send_email(
        to,
        "Reset your Iasty password",
        html,
        f"Reset your password: {link}",
    )


def send_account_deactivated_email(to: str, username: str, reason: str) -> bool:
    safe_username = escape(username)
    safe_reason = escape(reason)
    html = _email_shell(
        "Your Iasty account has been deactivated",
        f"""<p>Hi {safe_username},</p>
      <p>Your Iasty account has been deactivated by an administrator.</p>
      <p><strong>Reason:</strong> {safe_reason}</p>
      <p>If you believe this was a mistake, please contact support.</p>""",
    )
    return send_email(
        to,
        "Your Iasty account has been deactivated",
        html,
        f"Hi {username}, your Iasty account has been deactivated. Reason: {reason}",
    )


def send_account_reactivated_email(to: str, username: str) -> bool:
    link = settings.frontend_url.rstrip("/")
    safe_username = escape(username)
    html = _email_shell(
        "Your Iasty account is active again",
        f"""<p>Hi {safe_username},</p>
      <p>Your Iasty account has been reactivated. You can sign in and use the service again.</p>
      <p style="margin:24px 0;">
        <a href="{link}" style="background:#6366f1;color:#fff;padding:12px 18px;border-radius:8px;text-decoration:none;display:inline-block;">
          Open Iasty
        </a>
      </p>""",
    )
    return send_email(
        to,
        "Your Iasty account is active again",
        html,
        f"Hi {username}, your Iasty account has been reactivated. Sign in at {link}",
    )
