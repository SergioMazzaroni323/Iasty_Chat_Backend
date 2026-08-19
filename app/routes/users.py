from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_user_by_email, hash_password, user_to_response, verify_password
from app.database import get_db
from app.models import PlanType, User
from app.routes.auth import require_user, _send_verification_email_task
from app.schemas import PlanUpdateRequest, UpdateUserRequest, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserResponse)
def update_me(
    payload: UpdateUserRequest,
    background_tasks: BackgroundTasks,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    email_changed = False
    if user.is_removed:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.username is not None:
        user.username = payload.username
    if payload.email is not None and payload.email != user.email:
        existing = get_user_by_email(db, payload.email)
        if existing and existing.id != user.id:
            raise HTTPException(status_code=400, detail="Email already in use")
        user.email = payload.email
        user.email_verified = False
        email_changed = True
    if payload.new_password is not None:
        if not payload.current_password or not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user.hashed_password = hash_password(payload.new_password)
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    if email_changed:
        background_tasks.add_task(_send_verification_email_task, user.id)
    return user_to_response(user)


@router.post("/me/plan", response_model=UserResponse)
def update_plan(
    payload: PlanUpdateRequest,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if user.is_removed:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.plan not in ("free", "plus"):
        raise HTTPException(status_code=400, detail="Invalid plan")
    user.plan = PlanType.PLUS if payload.plan == "plus" else PlanType.FREE
    db.commit()
    db.refresh(user)
    return user_to_response(user)
