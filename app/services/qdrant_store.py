import asyncio

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.config import settings
from app.services.rag_types import (
    RetrievedChunk,
    get_vector_size,
    make_additional_data_point_id,
    make_point_id,
    owner_key,
)

_client: AsyncQdrantClient | None = None
_collection_ready = False
_init_lock = asyncio.Lock()


async def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        if settings.qdrant_url:
            _client = AsyncQdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
                timeout=settings.qdrant_timeout_seconds,
            )
        else:
            _client = AsyncQdrantClient(path=settings.qdrant_path)
    return _client


async def ensure_collection() -> None:
    global _collection_ready
    if _collection_ready:
        return

    async with _init_lock:
        if _collection_ready:
            return

        client = await get_client()
        collection = settings.qdrant_collection
        names = {item.name for item in (await client.get_collections()).collections}
        if collection not in names:
            await client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(
                    size=get_vector_size(),
                    distance=Distance.COSINE,
                ),
            )
        _collection_ready = True


async def upsert_message_chunks(
    *,
    chat_id: int,
    message_id: int,
    role: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    if not chunks or len(chunks) != len(embeddings):
        return

    await ensure_collection()
    client = await get_client()
    points = [
        PointStruct(
            id=make_point_id(message_id, index),
            vector=embedding,
            payload={
                "chat_id": chat_id,
                "message_id": message_id,
                "chunk_index": index,
                "role": role,
                "content": content,
            },
        )
        for index, (content, embedding) in enumerate(zip(chunks, embeddings))
    ]
    await client.upsert(collection_name=settings.qdrant_collection, points=points)


async def upsert_additional_data_chunks(
    *,
    data_id: int,
    owner: str,
    name: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> None:
    if not chunks or len(chunks) != len(embeddings):
        return

    await ensure_collection()
    client = await get_client()
    points = [
        PointStruct(
            id=make_additional_data_point_id(data_id, index),
            vector=embedding,
            payload={
                "source_type": "additional_data",
                "additional_data_id": data_id,
                "owner_key": owner,
                "name": name,
                "chunk_index": index,
                "content": content,
            },
        )
        for index, (content, embedding) in enumerate(zip(chunks, embeddings))
    ]
    await client.upsert(collection_name=settings.qdrant_collection, points=points)


async def search_similar(
    *,
    chat_id: int,
    query_embedding: list[float],
    top_k: int | None = None,
    exclude_message_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    await ensure_collection()
    client = await get_client()

    must = [FieldCondition(key="chat_id", match=MatchValue(value=chat_id))]
    must_not = [
        FieldCondition(key="message_id", match=MatchValue(value=message_id))
        for message_id in (exclude_message_ids or [])
    ]

    results = await client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_embedding,
        query_filter=Filter(must=must, must_not=must_not or None),
        limit=top_k or settings.rag_top_k,
        score_threshold=settings.rag_min_similarity,
    )

    return [
        RetrievedChunk(
            role=hit.payload.get("role", "assistant"),
            content=hit.payload.get("content", ""),
            score=hit.score,
        )
        for hit in results
        if hit.payload and hit.payload.get("content")
    ]


async def search_additional_data(
    *,
    owner: str,
    query_embedding: list[float],
    top_k: int | None = None,
    data_ids: list[int] | None = None,
) -> list[RetrievedChunk]:
    if data_ids is not None and not data_ids:
        return []

    await ensure_collection()
    client = await get_client()

    must = [
        FieldCondition(key="source_type", match=MatchValue(value="additional_data")),
        FieldCondition(key="owner_key", match=MatchValue(value=owner)),
    ]
    if data_ids is not None:
        must.append(FieldCondition(key="additional_data_id", match=MatchAny(any=data_ids)))

    results = await client.search(
        collection_name=settings.qdrant_collection,
        query_vector=query_embedding,
        query_filter=Filter(must=must),
        limit=top_k or settings.rag_top_k,
        score_threshold=settings.rag_min_similarity,
    )

    return [
        RetrievedChunk(
            role="data",
            content=f"[{hit.payload.get('name', 'Data')}] {hit.payload.get('content', '')}",
            score=hit.score,
        )
        for hit in results
        if hit.payload and hit.payload.get("content")
    ]


async def delete_additional_data_vectors(data_id: int) -> None:
    await ensure_collection()
    client = await get_client()
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="additional_data_id", match=MatchValue(value=data_id))]
        ),
    )


async def delete_chat_vectors(chat_id: int) -> None:
    await ensure_collection()
    client = await get_client()
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="chat_id", match=MatchValue(value=chat_id))]
        ),
    )


async def delete_message_vectors(message_ids: list[int]) -> None:
    if not message_ids:
        return

    await ensure_collection()
    client = await get_client()
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=Filter(
            must=[FieldCondition(key="message_id", match=MatchAny(any=message_ids))]
        ),
    )


async def close_client() -> None:
    global _client, _collection_ready
    if _client is not None:
        await _client.close()
        _client = None
    _collection_ready = False
