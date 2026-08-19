import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth import get_allowed_models, get_tier, get_token_limit
from app.constants import (
    ASSISTANT_SYSTEM_PROMPT,
    AVAILABLE_MODELS,
    BASIC_MODEL,
    BASIC_TOKEN_LIMIT,
    FREE_TOKEN_LIMIT,
    MODEL_UNAVAILABLE_MESSAGE,
    PLUS_TOKEN_LIMIT,
    is_model_available,
    is_web_search_available,
)
from app.database import SessionLocal, get_db
from app.models import AdditionalData, Chat, ChatFolder, Message, User
from app.routes.auth import get_current_user
from app.schemas import (
    ChatCreate,
    ChatDetailResponse,
    ChatResponse,
    ChatUpdate,
    ConfigResponse,
    MessageResponse,
    ModelInfo,
    SendMessageRequest,
)
from app.services.llm import stream_chat
from app.services.pdf import build_document_context, format_user_message_for_storage
from app.services.qdrant_store import delete_chat_vectors, delete_message_vectors
from app.services.rag import index_message, prepare_rag_context
from app.services.serpapi import build_search_context, search_web
from app.services.tokens import count_tokens
from app.timezone import to_utc_iso, utc_now

router = APIRouter(tags=["chats"])


def filter_owned_additional_data_ids(
    db: Session,
    user_id: int | None,
    guest_id: str | None,
    ids: list[int],
) -> list[int]:
    if not ids:
        return []
    query = db.query(AdditionalData.id).filter(AdditionalData.id.in_(ids))
    if user_id is not None:
        query = query.filter(AdditionalData.user_id == user_id)
    elif guest_id:
        query = query.filter(AdditionalData.guest_id == guest_id)
    else:
        return []
    return [row.id for row in query.all()]


def chat_token_used(chat: Chat) -> int:
    return sum(m.token_count for m in chat.messages)


def chat_to_response(chat: Chat, tier: str) -> ChatResponse:
    used = chat_token_used(chat)
    limit = get_token_limit(tier)
    return ChatResponse(
        id=chat.id,
        name=chat.name,
        folder_id=chat.folder_id,
        token_used=used,
        token_limit=limit,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def get_chat_or_404(db: Session, chat_id: int, user: User | None, guest_id: str | None) -> Chat:
    chat = db.query(Chat).filter(Chat.id == chat_id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    if user:
        if chat.user_id != user.id:
            raise HTTPException(status_code=403, detail="Forbidden")
    elif guest_id:
        if chat.guest_id != guest_id:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        raise HTTPException(status_code=403, detail="Forbidden")
    return chat


@router.get("/config", response_model=ConfigResponse)
def get_config(user: Annotated[User | None, Depends(get_current_user)]):
    tier = get_tier(user, guest=user is None)
    return ConfigResponse(
        models=[
            ModelInfo(id=m["id"], name=m["name"], available=is_model_available(m["id"]))
            for m in AVAILABLE_MODELS
        ],
        basic_model=BASIC_MODEL,
        tiers={
            "basic": {"token_limit": BASIC_TOKEN_LIMIT, "web_search": False, "models": 1},
            "free": {"token_limit": FREE_TOKEN_LIMIT, "web_search": False, "models": "all"},
            "plus": {"token_limit": PLUS_TOKEN_LIMIT, "web_search": True, "models": "all"},
        },
        current_tier=tier,
        allowed_models=get_allowed_models(tier),
        web_search_available=is_web_search_available(),
    )


@router.get("/chats", response_model=list[ChatResponse])
def list_chats(
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    tier = get_tier(user, guest=user is None)
    if user:
        chats = db.query(Chat).filter(Chat.user_id == user.id).order_by(Chat.updated_at.desc()).all()
    elif guest_id:
        chats = db.query(Chat).filter(Chat.guest_id == guest_id).order_by(Chat.updated_at.desc()).all()
    else:
        chats = []
    return [chat_to_response(c, tier) for c in chats]


@router.post("/chats", response_model=ChatResponse)
def create_chat(
    payload: ChatCreate,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    tier = get_tier(user, guest=user is None)
    chat = Chat(
        name=payload.name,
        user_id=user.id if user else None,
        guest_id=None if user else payload.guest_id,
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat_to_response(chat, tier)


@router.get("/chats/{chat_id}", response_model=ChatDetailResponse)
def get_chat(
    chat_id: int,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    tier = get_tier(user, guest=user is None)
    chat = get_chat_or_404(db, chat_id, user, guest_id)
    base = chat_to_response(chat, tier)
    return ChatDetailResponse(
        **base.model_dump(),
        messages=[MessageResponse.model_validate(m) for m in chat.messages],
    )


@router.patch("/chats/{chat_id}", response_model=ChatResponse)
def update_chat(
    chat_id: int,
    payload: ChatUpdate,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    tier = get_tier(user, guest=user is None)
    chat = get_chat_or_404(db, chat_id, user, guest_id)
    updates = payload.model_dump(exclude_unset=True)
    if "name" in updates and updates["name"] is not None:
        chat.name = updates["name"]
    if "folder_id" in updates:
        folder_id = updates["folder_id"]
        if folder_id is not None:
            if not user:
                raise HTTPException(status_code=403, detail="Folders require a signed-in account")
            folder = (
                db.query(ChatFolder)
                .filter(ChatFolder.id == folder_id, ChatFolder.user_id == user.id)
                .first()
            )
            if not folder:
                raise HTTPException(status_code=404, detail="Folder not found")
        chat.folder_id = folder_id
    db.commit()
    db.refresh(chat)
    return chat_to_response(chat, tier)


@router.post("/chats/{chat_id}/duplicate", response_model=ChatResponse)
def duplicate_chat(
    chat_id: int,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    tier = get_tier(user, guest=user is None)
    chat = get_chat_or_404(db, chat_id, user, guest_id)
    new_chat = Chat(
        name=f"{chat.name} (copy)",
        user_id=user.id if user else None,
        guest_id=None if user else guest_id,
        folder_id=chat.folder_id if user else None,
    )
    db.add(new_chat)
    db.flush()
    for msg in chat.messages:
        db.add(
            Message(
                chat_id=new_chat.id,
                role=msg.role,
                content=msg.content,
                token_count=msg.token_count,
            )
        )
    db.commit()
    db.refresh(new_chat)
    asyncio.run(_index_chat_messages(new_chat.id))
    return chat_to_response(new_chat, tier)


@router.delete("/chats/{chat_id}")
def delete_chat(
    chat_id: int,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    guest_id: str | None = None,
):
    chat = get_chat_or_404(db, chat_id, user, guest_id)
    asyncio.run(delete_chat_vectors(chat_id))
    db.delete(chat)
    db.commit()
    return {"ok": True}


@router.post("/chats/{chat_id}/messages")
async def send_message(
    chat_id: int,
    payload: SendMessageRequest,
    user: Annotated[User | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    guest_id = payload.guest_id
    tier = get_tier(user, guest=user is None)
    chat = get_chat_or_404(db, chat_id, user, guest_id)
    token_limit = get_token_limit(tier)
    allowed_models = get_allowed_models(tier)

    if payload.model not in allowed_models:
        raise HTTPException(status_code=400, detail="Model not allowed for your tier")

    if not is_model_available(payload.model):
        raise HTTPException(status_code=503, detail=MODEL_UNAVAILABLE_MESSAGE)

    web_search = payload.web_search and tier == "plus" and is_web_search_available()
    if payload.web_search and tier != "plus":
        raise HTTPException(status_code=403, detail="Web search requires Plus plan")

    if payload.edit_message_id:
        edit_msg = db.query(Message).filter(Message.id == payload.edit_message_id, Message.chat_id == chat_id).first()
        if not edit_msg:
            raise HTTPException(status_code=404, detail="Message not found")
        deleted_ids = [msg.id for msg in chat.messages if msg.created_at >= edit_msg.created_at]
        for msg in list(chat.messages):
            if msg.created_at >= edit_msg.created_at:
                db.delete(msg)
        db.commit()
        db.refresh(chat)
        if deleted_ids:
            asyncio.run(delete_message_vectors(deleted_ids))

    user_content = format_user_message_for_storage(
        payload.content,
        payload.document_filename,
        payload.document_text,
    )
    user_tokens = count_tokens(user_content)
    current_used = chat_token_used(chat)
    if current_used + user_tokens > token_limit:
        raise HTTPException(status_code=400, detail="Thread token limit reached")

    user_message = Message(
        chat_id=chat.id,
        role="user",
        content=user_content,
        token_count=user_tokens,
        created_at=utc_now(),
    )
    db.add(user_message)

    if chat.name == "New Chat":
        name_source = payload.content.strip() or payload.document_filename or "PDF Chat"
        chat.name = name_source[:80] + ("..." if len(name_source) > 80 else "")

    db.commit()
    db.refresh(chat)
    db.refresh(user_message)

    chat_id_val = chat.id
    user_message_id = user_message.id
    user_id_val = user.id if user else None
    rag_guest_id = guest_id if not user else None
    updated_name = chat.name
    updated_used = chat_token_used(chat)
    user_message_created_at_val = to_utc_iso(user_message.created_at)

    async def event_generator():
        yield _sse(
            "chat_updated",
            {
                "name": updated_name,
                "token_used": updated_used,
                "token_limit": token_limit,
                "user_message_id": user_message_id,
                "user_message_tokens": user_tokens,
                "user_message_created_at": user_message_created_at_val,
            },
        )

        assistant_content = ""
        search_results = []

        if web_search:
            yield _sse("search_start", {})
            try:
                search_results = await search_web(payload.content)
                for result in search_results:
                    if result.get("url"):
                        yield _sse("search_source", {"url": result["url"]})
                        await asyncio.sleep(0.8)
                yield _sse("search_done", {})
            except Exception as exc:
                yield _sse("error", {"message": f"Web search failed: {exc}"})

        rag_db = SessionLocal()
        try:
            stored_messages = (
                rag_db.query(Message)
                .filter(Message.chat_id == chat_id_val)
                .order_by(Message.created_at.asc())
                .all()
            )
            search_query = payload.content.strip() or payload.document_filename or "document"
            owned_data_ids = filter_owned_additional_data_ids(
                rag_db,
                user_id_val,
                rag_guest_id,
                payload.additional_data_ids,
            )
            rag_context, llm_history = await prepare_rag_context(
                rag_db,
                chat_id_val,
                search_query,
                stored_messages,
                user_id=user_id_val,
                guest_id=rag_guest_id,
                additional_data_ids=owned_data_ids,
            )
        finally:
            rag_db.close()

        llm_messages = [{"role": "system", "content": ASSISTANT_SYSTEM_PROMPT}]
        insert_at = 1
        if rag_context:
            llm_messages.insert(
                insert_at,
                {"role": "system", "content": rag_context},
            )
            insert_at += 1
        if payload.document_text and payload.document_filename:
            llm_messages.insert(
                insert_at,
                {
                    "role": "system",
                    "content": build_document_context(payload.document_filename, payload.document_text),
                },
            )
            insert_at += 1
        if search_results:
            llm_messages.insert(
                insert_at,
                {"role": "system", "content": build_search_context(search_results)},
            )
        llm_messages.extend(llm_history)

        async for chunk in stream_chat(llm_messages, payload.model):
            if chunk.startswith("event: token"):
                data_line = chunk.split("data: ", 1)[1].strip()
                data = json.loads(data_line)
                assistant_content += data.get("content", "")
            yield chunk

        assistant_tokens = count_tokens(assistant_content)
        save_db = SessionLocal()
        try:
            assistant_message = Message(
                chat_id=chat_id_val,
                role="assistant",
                content=assistant_content,
                token_count=assistant_tokens,
                created_at=utc_now(),
            )
            save_db.add(assistant_message)
            save_db.commit()
            save_db.refresh(assistant_message)
            await index_message(save_db, assistant_message)
            save_db.commit()
            saved_chat = save_db.query(Chat).filter(Chat.id == chat_id_val).first()
            used = sum(m.token_count for m in saved_chat.messages) if saved_chat else 0
            yield _sse(
                "usage",
                {
                    "token_used": used,
                    "token_limit": token_limit,
                    "user_message_id": user_message_id,
                    "user_message_tokens": user_tokens,
                    "assistant_message_id": assistant_message.id,
                    "assistant_message_tokens": assistant_tokens,
                    "assistant_message_created_at": to_utc_iso(assistant_message.created_at),
                },
            )
        finally:
            save_db.close()
        yield _sse("done", {})

    return StreamingResponse(event_generator(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _index_chat_messages(chat_id: int) -> None:
    from app.services.rag import ensure_chat_indexed

    db = SessionLocal()
    try:
        await ensure_chat_indexed(db, chat_id)
    finally:
        db.close()
