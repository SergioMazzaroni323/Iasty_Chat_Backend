from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AdditionalData, Chat, Message, PlanType, User
from app.routes.auth import require_user
from app.schemas import (
    AdditionalDataResponse,
    AdminChatResponse,
    AdminStatsResponse,
    AdminUserResponse,
    AdminUserUpdateRequest,
)

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
    total_tokens = db.query(func.coalesce(func.sum(Message.token_count), 0)).scalar() or 0
    return AdminStatsResponse(
        total_users=total_users,
        plus_users=plus_users,
        free_users=free_users,
        total_chats=total_chats,
        guest_chats=guest_chats,
        total_messages=total_messages,
        total_tokens=total_tokens,
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
        token_used = (
            db.query(func.coalesce(func.sum(Message.token_count), 0))
            .join(Chat, Message.chat_id == Chat.id)
            .filter(Chat.user_id == user.id)
            .scalar()
            or 0
        )
        additional_data_count = (
            db.query(func.count(AdditionalData.id)).filter(AdditionalData.user_id == user.id).scalar() or 0
        )
        result.append(
            AdminUserResponse(
                id=user.id,
                email=user.email,
                username=user.username,
                plan=user.plan.value,
                is_admin=user.is_admin,
                chat_count=chat_count,
                token_used=token_used,
                additional_data_count=additional_data_count,
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
    token_used = (
        db.query(func.coalesce(func.sum(Message.token_count), 0))
        .join(Chat, Message.chat_id == Chat.id)
        .filter(Chat.user_id == user.id)
        .scalar()
        or 0
    )
    additional_data_count = (
        db.query(func.count(AdditionalData.id)).filter(AdditionalData.user_id == user.id).scalar() or 0
    )
    return AdminUserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        plan=user.plan.value,
        is_admin=user.is_admin,
        chat_count=chat_count,
        token_used=token_used,
        additional_data_count=additional_data_count,
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
    search: str | None = None,
    user_id: int | None = Query(default=None, description="Filter by registered user_id"),
    include_guests: bool = Query(default=False, description="Include guest chats (guest_id is not null)"),
    min_tokens: int | None = None,
    max_tokens: int | None = None,
    min_messages: int | None = None,
    max_messages: int | None = None,
    sort_by: str = Query(default="updated_at", description="Sort by: updated_at|created_at|message_count|token_used"),
    sort_dir: str = Query(default="desc", description="Sort direction: asc|desc"),
    limit: int = Query(default=50, le=200),
):
    # Aggregate per-chat stats so we can filter/sort by message/token usage.
    msg_agg = (
        db.query(
            Message.chat_id.label("chat_id"),
            func.count(Message.id).label("message_count"),
            func.coalesce(func.sum(Message.token_count), 0).label("token_used"),
        )
        .group_by(Message.chat_id)
        .subquery()
    )

    token_expr = func.coalesce(msg_agg.c.token_used, 0)
    msg_count_expr = func.coalesce(msg_agg.c.message_count, 0)

    q = (
        db.query(Chat, User.username.label("username"), msg_count_expr.label("message_count"), token_expr.label("token_used"))
        .outerjoin(User, Chat.user_id == User.id)
        .outerjoin(msg_agg, msg_agg.c.chat_id == Chat.id)
    )

    if not include_guests:
        q = q.filter(Chat.user_id.is_not(None))
    if user_id is not None:
        q = q.filter(Chat.user_id == user_id)
    if search:
        q = q.filter(Chat.name.ilike(f"%{search}%"))

    if min_tokens is not None:
        q = q.filter(token_expr >= min_tokens)
    if max_tokens is not None:
        q = q.filter(token_expr <= max_tokens)

    if min_messages is not None:
        q = q.filter(msg_count_expr >= min_messages)
    if max_messages is not None:
        q = q.filter(msg_count_expr <= max_messages)

    sort_column = Chat.updated_at
    if sort_by == "created_at":
        sort_column = Chat.created_at
    elif sort_by == "message_count":
        sort_column = msg_count_expr
    elif sort_by == "token_used":
        sort_column = token_expr
    # else: default updated_at

    if sort_dir.lower() == "asc":
        q = q.order_by(sort_column.asc())
    else:
        q = q.order_by(sort_column.desc())

    chats = q.limit(limit).all()

    result: list[AdminChatResponse] = []
    for chat, username, message_count, token_used in chats:
        result.append(
            AdminChatResponse(
                id=chat.id,
                name=chat.name,
                user_id=chat.user_id,
                username=username,
                message_count=int(message_count or 0),
                token_used=int(token_used or 0),
                created_at=chat.created_at,
                updated_at=chat.updated_at,
            )
        )
    return result


@router.get("/users/{user_id}/additional-data", response_model=list[AdditionalDataResponse])
def list_user_additional_data(
    user_id: int,
    admin: Annotated[User, Depends(require_admin)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=50, le=200),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    items = (
        db.query(AdditionalData)
        .filter(AdditionalData.user_id == user_id)
        .order_by(AdditionalData.updated_at.desc())
        .limit(limit)
        .all()
    )
    return [AdditionalDataResponse.model_validate(item) for item in items]


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
