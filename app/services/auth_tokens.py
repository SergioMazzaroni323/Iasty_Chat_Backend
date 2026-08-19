import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthToken, User
from app.services.email import (
    PURPOSE_PASSWORD_RESET,
    PURPOSE_VERIFY_EMAIL,
    send_password_reset_email,
    send_verification_email,
)


def _expires_at(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def _clear_tokens(db: Session, user_id: int, purpose: str) -> None:
    db.query(AuthToken).filter(AuthToken.user_id == user_id, AuthToken.purpose == purpose).delete()


def create_token(db: Session, user: User, purpose: str, hours: int) -> str:
    _clear_tokens(db, user.id, purpose)
    raw = secrets.token_urlsafe(32)
    db.add(
        AuthToken(
            user_id=user.id,
            token=raw,
            purpose=purpose,
            expires_at=_expires_at(hours),
        )
    )
    db.commit()
    return raw


def consume_token(db: Session, raw: str, purpose: str) -> User | None:
    token = db.query(AuthToken).filter(AuthToken.token == raw, AuthToken.purpose == purpose).first()
    if not token:
        return None

    now = datetime.now(timezone.utc)
    expires_at = token.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    user = db.query(User).filter(User.id == token.user_id).first()
    db.delete(token)
    db.commit()

    if not user or expires_at < now:
        return None
    return user


def issue_verification_email(db: Session, user: User) -> bool:
    raw = create_token(db, user, PURPOSE_VERIFY_EMAIL, settings.email_verify_expire_hours)
    return send_verification_email(user.email, raw)


def issue_password_reset_email(db: Session, user: User) -> bool:
    raw = create_token(db, user, PURPOSE_PASSWORD_RESET, settings.password_reset_expire_hours)
    return send_password_reset_email(user.email, raw)
