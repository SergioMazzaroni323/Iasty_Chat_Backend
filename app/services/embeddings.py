import hashlib
import math
import re

import httpx

from app.config import settings

LOCAL_EMBED_DIM = 384
_token_re = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return _token_re.findall(text.lower())


def local_embed(text: str, dim: int = LOCAL_EMBED_DIM) -> list[float]:
    vector = [0.0] * dim
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


async def embed_texts(texts: list[str]) -> list[list[float]]:
    cleaned = [text.strip() for text in texts if text and text.strip()]
    if not cleaned:
        return []

    if settings.openai_api_key:
        try:
            return await _openai_embed(cleaned)
        except Exception:
            pass

    return [local_embed(text) for text in cleaned]


async def _openai_embed(texts: list[str]) -> list[list[float]]:
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.embedding_model,
        "input": texts,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/embeddings",
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    items = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
    return [item["embedding"] for item in items]
