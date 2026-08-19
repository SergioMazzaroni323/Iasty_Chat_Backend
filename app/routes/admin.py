from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Chat, Message, PlanType, User
from app.routes.auth import require_user
from app.schemas import AdminChatResponse, AdminStatsResponse, AdminUserResponse, AdminUserUpdateRequest

router = APIRouter(prefix="/admin", tags=["admin"])


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/stats", response_model=AdminStatsResponse)
def get_stats(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    total_users = db.query(func.count(User.id)).scalar() or 0
    plus_users = db.query(func.count(User.id)).filter(User.plan == PlanType.PLUS).scalar() or 0
    free_users = db.query(func.count(User.id)).filter(User.plan == PlanType.FREE).scalar() or 0
    total_chats = db.query(func.count(Chat.id)).scalar() or 0
    guest_chats = db.query(func.count(Chat.id)).filter(Chat.user_id.is_(None)).scalar() or 0
    total_messages = db.query(func.count(Message.id)).scalar() or 0
    return AdminStatsResponse(
        total_users=total_users,
        plus_users=plus_users,
        free_users=free_users,
        total_chats=total_chats,
        guest_chats=guest_chats,
        total_messages=total_messages,
    )


@router.get("/users", response_model=list[AdminUserResponse])
def list_users(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    result = []
    for user in users:
        chat_count = db.query(func.count(Chat.id)).filter(Chat.user_id == user.id).scalar() or 0
        result.append(
            AdminUserResponse(
                id=user.id,
                email=user.email,
                username=user.username,
                plan=user.plan.value,
                is_admin=user.is_admin,
                chat_count=chat_count,
                created_at=user.created_at,
            )
        )
    return result


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
def update_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and payload.is_admin is False:
        raise HTTPException(status_code=400, detail="Cannot remove your own admin access")

    if payload.plan is not None:
        if payload.plan not in ("free", "plus"):
            raise HTTPException(status_code=400, detail="Invalid plan")
        user.plan = PlanType.PLUS if payload.plan == "plus" else PlanType.FREE

    if payload.is_admin is not None:
        user.is_admin = payload.is_admin

    db.commit()
    db.refresh(user)
    chat_count = db.query(func.count(Chat.id)).filter(Chat.user_id == user.id).scalar() or 0
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        plan=user.plan.value,
        is_admin=user.is_admin,
        chat_count=chat_count,
        created_at=user.created_at,
    )


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"ok": True}


@router.get("/chats", response_model=list[AdminChatResponse])
def list_chats(
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = 50,
):
    chats = db.query(Chat).order_by(Chat.updated_at.desc()).limit(limit).all()
    result = []
    for chat in chats:
        message_count = db.query(func.count(Message.id)).filter(Message.chat_id == chat.id).scalar() or 0
        username = chat.user.username if chat.user else None
        result.append(
            AdminChatResponse(
                id=chat.id,
                name=chat.name,
                user_id=chat.user_id,
                username=username,
                message_count=message_count,
                created_at=chat.created_at,
                updated_at=chat.updated_at,
            )
        )
    return result


@router.delete("/chats/{chat_id}")
def delete_chat(
    chat_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
):
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    db.delete(chat)
    db.commit()
    return {"ok": True}
