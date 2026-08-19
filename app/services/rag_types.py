from dataclasses import dataclass

from app.config import settings


@dataclass
class RetrievedChunk:
    role: str
    content: str
    score: float


def get_vector_size() -> int:
    if settings.openai_api_key:
        return 1536
    return 384


def make_point_id(message_id: int, chunk_index: int) -> int:
    return message_id * 1000 + chunk_index


def make_additional_data_point_id(data_id: int, chunk_index: int) -> int:
    return 2_000_000_000 + data_id * 10_000 + chunk_index


def owner_key(user_id: int | None, guest_id: str | None) -> str | None:
    if user_id is not None:
        return f"user:{user_id}"
    if guest_id:
        return f"guest:{guest_id}"
    return None
