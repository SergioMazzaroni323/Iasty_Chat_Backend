import json
from typing import AsyncGenerator

from app.config import settings
from app.constants import OPENAI_MODEL_IDS, resolve_provider, to_openrouter_model
from app.services import openai, openrouter
from app.services.errors import is_region_blocked_message


async def stream_chat(messages: list[dict], model: str) -> AsyncGenerator[str, None]:
    provider = resolve_provider(model)

    if provider == "openrouter" and model in OPENAI_MODEL_IDS:
        or_model = to_openrouter_model(model)
        async for chunk in openrouter.stream_chat(messages, or_model):
            yield chunk
        return

    if provider == "openai":
        region_blocked = False
        async for chunk in openai.stream_chat(messages, model):
            if _is_error_event(chunk):
                message = _error_message(chunk)
                if settings.openrouter_api_key and is_region_blocked_message(message):
                    region_blocked = True
                    break
                yield chunk
                return
            yield chunk

        if region_blocked:
            or_model = to_openrouter_model(model)
            async for chunk in openrouter.stream_chat(messages, or_model):
                yield chunk
        return

    async for chunk in openrouter.stream_chat(messages, model):
        yield chunk


def _is_error_event(chunk: str) -> bool:
    return chunk.startswith("event: error")


def _error_message(chunk: str) -> str:
    for line in chunk.split("\n"):
        if line.startswith("data: "):
            try:
                return json.loads(line[6:]).get("message", "")
            except json.JSONDecodeError:
                return line[6:]
    return ""
