from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token,
    decode_token,
    get_user_by_email,
    get_user_by_id,
    hash_password,
    user_to_response,
    verify_password,
)
from app.database import SessionLocal, get_db
from app.db_init import maybe_promote_admin
from app.models import PlanType, User
from app.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendRegistrationRequest,
    ResetPasswordRequest,
    StatusMessageResponse,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from app.services.auth_tokens import (
    consume_token,
    issue_password_reset_email,
    issue_verification_email,
)
from app.services.email import PURPOSE_PASSWORD_RESET, PURPOSE_VERIFY_EMAIL, email_configured, get_last_email_error
from app.services.pending_registration import (
    consume_pending_registration,
    get_pending_by_email,
    pending_password_matches,
    resend_pending_registration_email,
    send_pending_registration_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    if not credentials:
        return None
    user_id = decode_token(credentials.credentials)
    if not user_id:
        return None
    return get_user_by_id(db, user_id)


def require_user(user: Annotated[User | None, Depends(get_current_user)]) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def _send_verification_email_task(user_id: int) -> None:
    db = SessionLocal()
    try:
        user = get_user_by_id(db, user_id)
        if user and not user.email_verified:
            sent = issue_verification_email(db, user)
            if not sent:
                import logging

                logging.getLogger(__name__).error(
                    "Failed to send verification email to user_id=%s", user_id
                )
    finally:
        db.close()


def _require_email() -> None:
    if not email_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email is not configured. Add Gmail OAuth (EMAIL_PROVIDER=gmail), RESEND_API_KEY, or SMTP settings.",
        )


@router.post("/register", response_model=StatusMessageResponse)
def register(payload: RegisterRequest, db: Annotated[Session, Depends(get_db)]):
    _require_email()
    if get_user_by_email(db, payload.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if not send_pending_registration_email(db, payload.email, payload.username, payload.password):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=get_last_email_error() or "Failed to send verification email.",
        )
    return StatusMessageResponse(
        message="Verification link sent to your email. Please check your inbox or Spam folder."
    )


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Annotated[Session, Depends(get_db)]):
    user = get_user_by_email(db, payload.email)
    if user:
        if not verify_password(payload.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Please verify your email before signing in.",
            )
        maybe_promote_admin(user, db)
        return TokenResponse(access_token=create_access_token(user.id))

    if pending_password_matches(db, payload.email, payload.password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please complete registration using the verification link sent to your email.",
        )
    raise HTTPException(status_code=401, detail="Invalid email or password")


@router.get("/me", response_model=UserResponse | None)
def me(user: Annotated[User | None, Depends(get_current_user)]):
    return user_to_response(user)


@router.post("/verify-email", response_model=VerifyEmailResponse)
def verify_email(payload: VerifyEmailRequest, db: Annotated[Session, Depends(get_db)]):
    pending = consume_pending_registration(db, payload.token)
    if pending:
        if get_user_by_email(db, pending.email):
            raise HTTPException(status_code=400, detail="Email already registered")
        user = User(
            email=pending.email,
            username=pending.username,
            hashed_password=pending.hashed_password,
            plan=PlanType.FREE,
            email_verified=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        maybe_promote_admin(user, db)
        return VerifyEmailResponse(
            message="Account created successfully. You are now signed in.",
            access_token=create_access_token(user.id),
        )

    user = consume_token(db, payload.token, PURPOSE_VERIFY_EMAIL)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")
    user.email_verified = True
    db.commit()
    return VerifyEmailResponse(
        message="Email verified successfully.",
        access_token=create_access_token(user.id),
    )


@router.post("/resend-registration", response_model=StatusMessageResponse)
def resend_registration(payload: ResendRegistrationRequest, db: Annotated[Session, Depends(get_db)]):
    _require_email()
    if get_user_by_email(db, payload.email):
        return StatusMessageResponse(message="If that email is pending verification, a new link has been sent.")
    if not get_pending_by_email(db, payload.email):
        return StatusMessageResponse(message="If that email is pending verification, a new link has been sent.")
    if not resend_pending_registration_email(db, payload.email):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=get_last_email_error() or "Failed to send verification email.",
        )
    return StatusMessageResponse(message="Verification email sent. Check your inbox.")


@router.post("/resend-verification", response_model=StatusMessageResponse)
def resend_verification(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if user.email_verified:
        return StatusMessageResponse(message="Email is already verified")
    _require_email()
    if not issue_verification_email(db, user):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=get_last_email_error() or "Failed to send verification email.",
        )
    return StatusMessageResponse(message="Verification email sent")


@router.post("/forgot-password", response_model=StatusMessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Annotated[Session, Depends(get_db)],
):
    _require_email()
    user = get_user_by_email(db, payload.email)
    if user and not issue_password_reset_email(db, user):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=get_last_email_error() or "Failed to send reset email.",
        )
    return StatusMessageResponse(message="If that email exists, a reset link has been sent")


@router.post("/reset-password", response_model=StatusMessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Annotated[Session, Depends(get_db)]):
    user = consume_token(db, payload.token, PURPOSE_PASSWORD_RESET)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    user.hashed_password = hash_password(payload.new_password)
    db.commit()
    return StatusMessageResponse(message="Password updated successfully")
