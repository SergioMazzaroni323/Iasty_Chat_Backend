import asyncio
import re

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AdditionalData, Message
from app.services.embeddings import embed_texts
from app.services.qdrant_store import (
    delete_additional_data_vectors,
    search_additional_data,
    search_similar,
    upsert_additional_data_chunks,
    upsert_message_chunks,
)
from app.services.rag_types import RetrievedChunk, owner_key

_sentence_split_re = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def split_into_chunks(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    sentences = [part.strip() for part in _sentence_split_re.split(text) if part.strip()]
    if not sentences:
        return [text[: settings.rag_chunk_size]]

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= settings.rag_chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)
        if len(sentence) <= settings.rag_chunk_size:
            current = sentence
        else:
            for start in range(0, len(sentence), settings.rag_chunk_size):
                chunks.append(sentence[start : start + settings.rag_chunk_size])
            current = ""

    if current:
        chunks.append(current)

    return chunks


def build_rag_context(chunks: list[RetrievedChunk], title: str | None = None) -> str:
    heading = title or "Relevant excerpts from earlier in this conversation. Use them for context when answering."
    lines = [heading, ""]
    for index, chunk in enumerate(chunks, 1):
        if chunk.role == "data":
            lines.append(f"[{index}] {chunk.content}")
            continue
        role_label = "User" if chunk.role == "user" else "Assistant"
        lines.append(f"[{index}] ({role_label}) {chunk.content}")
    return "\n".join(lines)


async def index_additional_data(db: Session, item: AdditionalData) -> None:
    if item.rag_indexed or not item.content.strip():
        if not item.content.strip():
            item.rag_indexed = True
        return

    key = owner_key(item.user_id, item.guest_id)
    if not key:
        return

    chunks = split_into_chunks(item.content)
    if not chunks:
        item.rag_indexed = True
        return

    embeddings = await embed_texts(chunks)
    if len(embeddings) != len(chunks):
        return

    await upsert_additional_data_chunks(
        data_id=item.id,
        owner=key,
        name=item.name,
        chunks=chunks,
        embeddings=embeddings,
    )
    item.rag_indexed = True


async def delete_additional_data_index(data_id: int) -> None:
    await delete_additional_data_vectors(data_id)


async def search_additional_data_chunks(
    user_id: int | None,
    guest_id: str | None,
    query: str,
    *,
    query_embedding: list[float] | None = None,
    top_k: int | None = None,
    data_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    key = owner_key(user_id, guest_id)
    if not key:
        return []

    if data_ids is not None and not data_ids:
        return []

    query = query.strip()
    if not query and query_embedding is None:
        return []

    if query_embedding is None:
        embeddings = await embed_texts([query])
        if not embeddings:
            return []
        query_embedding = embeddings[0]

    return await search_additional_data(
        owner=key,
        query_embedding=query_embedding,
        top_k=top_k,
        data_ids=data_ids,
    )


async def index_message(db: Session, message: Message) -> None:
    if message.rag_indexed:
        return

    chunks = split_into_chunks(message.content)
    if not chunks:
        message.rag_indexed = True
        return

    embeddings = await embed_texts(chunks)
    if len(embeddings) != len(chunks):
        return

    await upsert_message_chunks(
        chat_id=message.chat_id,
        message_id=message.id,
        role=message.role,
        chunks=chunks,
        embeddings=embeddings,
    )
    message.rag_indexed = True


async def ensure_chat_indexed(db: Session, chat_id: int) -> None:
    pending = (
        db.query(Message)
        .filter(Message.chat_id == chat_id, Message.rag_indexed.is_(False))
        .order_by(Message.created_at.asc())
        .all()
    )
    if not pending:
        return

    batch: list[tuple[Message, int, str]] = []
    empty_messages: list[Message] = []

    for message in pending:
        chunks = split_into_chunks(message.content)
        if not chunks:
            empty_messages.append(message)
            continue
        for index, content in enumerate(chunks):
            batch.append((message, index, content))

    for message in empty_messages:
        message.rag_indexed = True

    if batch:
        embeddings = await embed_texts([content for _, _, content in batch])
        if len(embeddings) != len(batch):
            return

        grouped: dict[int, dict] = {}
        for (message, chunk_index, content), embedding in zip(batch, embeddings):
            entry = grouped.setdefault(message.id, {"message": message, "pairs": []})
            entry["pairs"].append((chunk_index, content, embedding))

        for entry in grouped.values():
            message = entry["message"]
            pairs = sorted(entry["pairs"], key=lambda item: item[0])
            chunks = [content for _, content, _ in pairs]
            vectors = [vector for _, _, vector in pairs]
            await upsert_message_chunks(
                chat_id=message.chat_id,
                message_id=message.id,
                role=message.role,
                chunks=chunks,
                embeddings=vectors,
            )
            message.rag_indexed = True

    db.commit()


async def search_similar_chunks(
    chat_id: int,
    query: str,
    *,
    query_embedding: list[float] | None = None,
    top_k: int | None = None,
    exclude_message_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    query = query.strip()
    if not query and query_embedding is None:
        return []

    if query_embedding is None:
        embeddings = await embed_texts([query])
        if not embeddings:
            return []
        query_embedding = embeddings[0]

    return await search_similar(
        chat_id=chat_id,
        query_embedding=query_embedding,
        top_k=top_k,
        exclude_message_ids=exclude_message_ids,
    )


async def prepare_rag_context(
    db: Session,
    chat_id: int,
    query: str,
    messages: list[Message],
    *,
    user_id: int | None = None,
    guest_id: str | None = None,
    additional_data_ids: list[int] | None = None,
) -> tuple[str | None, list[dict]]:
    recent = messages[-settings.rag_recent_messages :]
    recent_history = [{"role": message.role, "content": message.content} for message in recent]
    full_history = [{"role": m.role, "content": m.content} for m in messages]

    try:
        embed_task = asyncio.create_task(embed_texts([query.strip() or "context"]))
        index_task = None
        recent_ids: list[int] = []

        if settings.rag_enabled and len(messages) >= settings.rag_min_messages:
            recent_ids = [message.id for message in recent]
            index_task = asyncio.create_task(ensure_chat_indexed(db, chat_id))

        if index_task:
            await index_task

        query_embeddings = await embed_task
        query_embedding = query_embeddings[0] if query_embeddings else None

        chat_chunks: list[RetrievedChunk] = []
        if settings.rag_enabled and len(messages) >= settings.rag_min_messages and query_embedding:
            chat_chunks = await search_similar_chunks(
                chat_id,
                query,
                query_embedding=query_embedding,
                exclude_message_ids=recent_ids,
            )

        additional_chunks: list[RetrievedChunk] = []
        if query_embedding and owner_key(user_id, guest_id):
            if additional_data_ids is None or additional_data_ids:
                additional_chunks = await search_additional_data_chunks(
                    user_id,
                    guest_id,
                    query,
                    query_embedding=query_embedding,
                    top_k=max(3, settings.rag_top_k // 2),
                    data_ids=additional_data_ids,
                )

        context_parts: list[str] = []
        if additional_chunks:
            context_parts.append(
                build_rag_context(
                    additional_chunks,
                    title="Relevant excerpts from the user's additional data. Use them when helpful.",
                )
            )
        if chat_chunks:
            context_parts.append(build_rag_context(chat_chunks))

        rag_context = "\n\n".join(context_parts) if context_parts else None
        history = recent_history if settings.rag_enabled and len(messages) >= settings.rag_min_messages else full_history
        return rag_context, history
    except Exception:
        history = recent_history if settings.rag_enabled and len(messages) >= settings.rag_min_messages else full_history
        return None, history
