from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AdditionalData, User
from app.routes.auth import get_current_user
from app.schemas import (
    AdditionalDataAppendRequest,
    AdditionalDataCreate,
    AdditionalDataResponse,
    AdditionalDataUpdate,
    ParseFilesResponse,
)
from app.services.file_parser import format_file_import, merge_content, parse_file_bytes
from app.services.rag import delete_additional_data_index, index_additional_data

router = APIRouter(prefix="/additional-data", tags=["additional-data"])

ALLOWED_EXTENSIONS = {".txt", ".pdf", ".docx", ".doc"}


def get_owner_filter(user: User | None, guest_id: str | None):
    if user:
        return (AdditionalData.user_id == user.id) & AdditionalData.is_removed.is_(False)
    if guest_id:
        return (AdditionalData.guest_id == guest_id) & AdditionalData.is_removed.is_(False)
    return None


def get_item_or_404(
    db: Session, item_id: int, user: User | None, guest_id: str | None
) -> AdditionalData:
    item = db.query(AdditionalData).filter(AdditionalData.id == item_id, AdditionalData.is_removed.is_(False)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Additional data not found")
    if user:
        if item.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif guest_id:
        if item.guest_id != guest_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")
    return item


@router.get("", response_model=list[AdditionalDataResponse])
def list_additional_data(
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    owner = get_owner_filter(user, guest_id)
    if owner is None:
        return []
    items = db.query(AdditionalData).filter(owner).order_by(AdditionalData.updated_at.desc()).all()
    return [AdditionalDataResponse.model_validate(item) for item in items]


@router.post("", response_model=AdditionalDataResponse)
async def create_additional_data(
    payload: AdditionalDataCreate,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if not user and not payload.guest_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    item = AdditionalData(
        name=payload.name.strip() or "Untitled",
        content=payload.content.strip(),
        user_id=user.id if user else None,
        guest_id=None if user else payload.guest_id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    await index_additional_data(db, item)
    db.commit()
    db.refresh(item)
    return AdditionalDataResponse.model_validate(item)


@router.get("/{item_id}", response_model=AdditionalDataResponse)
def get_additional_data(
    item_id: int,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    item = get_item_or_404(db, item_id, user, guest_id)
    return AdditionalDataResponse.model_validate(item)


@router.patch("/{item_id}", response_model=AdditionalDataResponse)
async def update_additional_data(
    item_id: int,
    payload: AdditionalDataUpdate,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    item = get_item_or_404(db, item_id, user, guest_id)
    if payload.name is not None:
        item.name = payload.name.strip() or item.name
    if payload.content is not None:
        item.content = payload.content
        item.rag_indexed = False
    db.commit()
    db.refresh(item)
    if payload.content is not None:
        await delete_additional_data_index(item.id)
        await index_additional_data(db, item)
        db.commit()
        db.refresh(item)
    return AdditionalDataResponse.model_validate(item)


@router.post("/{item_id}/append", response_model=AdditionalDataResponse)
async def append_additional_data(
    item_id: int,
    payload: AdditionalDataAppendRequest,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    item = get_item_or_404(db, item_id, user, guest_id)
    item.content = merge_content(item.content, payload.content)
    item.rag_indexed = False
    db.commit()
    db.refresh(item)
    await delete_additional_data_index(item.id)
    await index_additional_data(db, item)
    db.commit()
    db.refresh(item)
    return AdditionalDataResponse.model_validate(item)


@router.post("/{item_id}/duplicate", response_model=AdditionalDataResponse)
async def duplicate_additional_data(
    item_id: int,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    item = get_item_or_404(db, item_id, user, guest_id)
    copy = AdditionalData(
        name=f"{item.name} (copy)",
        content=item.content,
        user_id=user.id if user else None,
        guest_id=None if user else guest_id,
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    await index_additional_data(db, copy)
    db.commit()
    db.refresh(copy)
    return AdditionalDataResponse.model_validate(copy)


@router.delete("/{item_id}")
async def delete_additional_data(
    item_id: int,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    item = get_item_or_404(db, item_id, user, guest_id)
    await delete_additional_data_index(item.id)
    item.is_removed = True
    db.commit()
    return {"ok": True}


@router.post("/parse-files", response_model=ParseFilesResponse)
async def parse_files(files: Annotated[list[UploadFile], File()]):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    parsed_parts: list[str] = []
    file_names: list[str] = []

    for upload in files:
        filename = upload.filename or "file"
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {filename}")

        data = await upload.read()
        try:
            text = parse_file_bytes(filename, data)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse {filename}: {exc}") from exc

        if not text.strip():
            raise HTTPException(status_code=400, detail=f"No text extracted from {filename}")

        parsed_parts.append(format_file_import(filename, text))
        file_names.append(filename)

    combined = merge_content("", "\n\n".join(parsed_parts))
    return ParseFilesResponse(text=combined, filenames=file_names)
