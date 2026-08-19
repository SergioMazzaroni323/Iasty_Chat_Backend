from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Chat, ChatFolder, User
from app.routes.auth import require_user
from app.schemas import ChatFolderCreate, ChatFolderResponse, ChatFolderUpdate

router = APIRouter(prefix="/chat-folders", tags=["chat-folders"])


def get_folder_or_404(db: Session, folder_id: int, user: User) -> ChatFolder:
    folder = (
        db.query(ChatFolder)
        .filter(ChatFolder.id == folder_id, ChatFolder.user_id == user.id, ChatFolder.is_removed.is_(False))
        .first()
    )
    if not folder:
        raise HTTPException(status_code=404, detail="Folder not found")
    return folder


@router.get("", response_model=list[ChatFolderResponse])
def list_folders(
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    folders = (
        db.query(ChatFolder)
        .filter(ChatFolder.user_id == user.id, ChatFolder.is_removed.is_(False))
        .order_by(ChatFolder.created_at.asc())
        .all()
    )
    return folders


@router.post("", response_model=ChatFolderResponse)
def create_folder(
    payload: ChatFolderCreate,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    folder = ChatFolder(user_id=user.id, name=payload.name.strip())
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return folder


@router.patch("/{folder_id}", response_model=ChatFolderResponse)
def update_folder(
    folder_id: int,
    payload: ChatFolderUpdate,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    folder = get_folder_or_404(db, folder_id, user)
    folder.name = payload.name.strip()
    db.commit()
    db.refresh(folder)
    return folder


@router.delete("/{folder_id}")
def delete_folder(
    folder_id: int,
    user: Annotated[User, Depends(require_user)],
    db: Annotated[Session, Depends(get_db)],
):
    folder = get_folder_or_404(db, folder_id, user)
    db.query(Chat).filter(Chat.folder_id == folder.id).update({Chat.folder_id: None})
    folder.is_removed = True
    db.commit()
    return {"ok": True}
