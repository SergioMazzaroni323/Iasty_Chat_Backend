import secrets
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from sqlalchemy.orm import Session

from app.auth import hash_password, verify_password
from app.config import settings
from app.models import PendingRegistration
from app.services.email import send_verification_email


class PendingRegistrationData(NamedTuple):
    email: str
    username: str
    hashed_password: str


def _expires_at(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def get_pending_by_email(db: Session, email: str) -> PendingRegistration | None:
    return db.query(PendingRegistration).filter(PendingRegistration.email == email).first()


def create_pending_registration(db: Session, email: str, username: str, password: str) -> str:
    db.query(PendingRegistration).filter(PendingRegistration.email == email).delete()
    raw = secrets.token_urlsafe(32)
    db.add(
        PendingRegistration(
            email=email,
            username=username,
            hashed_password=hash_password(password),
            token=raw,
            expires_at=_expires_at(settings.email_verify_expire_hours),
        )
    )
    db.commit()
    return raw


def send_pending_registration_email(db: Session, email: str, username: str, password: str) -> bool:
    raw = create_pending_registration(db, email, username, password)
    return send_verification_email(email, raw)


def resend_pending_registration_email(db: Session, email: str) -> bool:
    pending = get_pending_by_email(db, email)
    if not pending:
        return False
    pending.token = secrets.token_urlsafe(32)
    pending.expires_at = _expires_at(settings.email_verify_expire_hours)
    db.commit()
    return send_verification_email(pending.email, pending.token)


def consume_pending_registration(db: Session, raw: str) -> PendingRegistrationData | None:
    pending = db.query(PendingRegistration).filter(PendingRegistration.token == raw).first()
    if not pending:
        return None

    now = datetime.now(timezone.utc)
    expires_at = pending.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    data = PendingRegistrationData(
        email=pending.email,
        username=pending.username,
        hashed_password=pending.hashed_password,
    )
    db.delete(pending)
    db.commit()

    if expires_at < now:
        return None
    return data


def pending_password_matches(db: Session, email: str, password: str) -> bool:
    pending = get_pending_by_email(db, email)
    if not pending:
        return False
    return verify_password(password, pending.hashed_password)
