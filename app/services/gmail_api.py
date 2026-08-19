import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.config import settings


class GmailSendError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def gmail_configured() -> bool:
    return bool(
        settings.gmail_client_id
        and settings.gmail_client_secret
        and settings.gmail_refresh_token
    )


def gmail_from_header() -> str:
    if settings.gmail_from:
        return settings.gmail_from
    sender = settings.gmail_sender or settings.smtp_from or settings.smtp_user
    return f"{settings.smtp_from_name} <{sender}>"


def _get_access_token() -> str:
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "refresh_token": settings.gmail_refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    if response.status_code >= 400:
        try:
            payload = response.json()
            message = payload.get("error_description") or payload.get("error") or response.text
        except Exception:
            message = response.text.strip() or response.reason_phrase
        raise GmailSendError(f"Gmail OAuth failed: {message}")
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise GmailSendError("Gmail OAuth did not return an access token")
    return token


def send_via_gmail(to: str, subject: str, html: str, text: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["From"] = gmail_from_header()
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(text or html, "plain"))
    msg.attach(MIMEText(html, "html"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    access_token = _get_access_token()

    response = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
        timeout=30.0,
    )
    if response.status_code >= 400:
        try:
            payload = response.json()
            message = payload.get("error", {}).get("message") or response.text.strip()
        except Exception:
            message = response.text.strip() or response.reason_phrase
        raise GmailSendError(message)
