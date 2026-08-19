import json
from typing import AsyncGenerator

import httpx

from app.config import settings
from app.services.errors import parse_api_error


async def stream_chat(
    messages: list[dict],
    model: str,
) -> AsyncGenerator[str, None]:
    if not settings.openai_api_key:
        yield _sse("error", {"message": "OpenAI API key not configured"})
        yield _sse("done", {})
        return

    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                yield _sse("error", {"message": parse_api_error(body.decode(), "OpenAI")})
                yield _sse("done", {})
                return

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if chunk.get("error"):
                    yield _sse(
                        "error",
                        {"message": parse_api_error(json.dumps(chunk), "OpenAI")},
                    )
                    yield _sse("done", {})
                    return

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield _sse("token", {"content": content})


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
