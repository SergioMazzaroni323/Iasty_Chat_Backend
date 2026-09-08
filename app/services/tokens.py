from math import ceil


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def count_messages_tokens(messages: list[dict]) -> int:
    total = 0
    for msg in messages:
        total += count_tokens(msg.get("content", "")) + 4
    return total


# OpenAI vision tile pricing (detail=high). gpt-4o-mini uses inflated image tokens.
_VISION_TILE_COSTS = {
    "gpt-4o-mini": (2833, 5667),
    "gpt-4o": (85, 170),
    "gpt-5.6-luna": (85, 170),
}


def estimate_openai_image_tokens(width: int, height: int, model_id: str) -> int:
    """Estimate image input tokens using OpenAI high-detail tiling rules."""
    if width <= 0 or height <= 0:
        return 0

    base, tile = _VISION_TILE_COSTS.get(model_id, (85, 170))

    # Scale to fit within 2048x2048
    w, h = float(width), float(height)
    if w > 2048 or h > 2048:
        scale = 2048 / max(w, h)
        w *= scale
        h *= scale

    # Scale so shortest side is 768px
    shortest = min(w, h)
    if shortest > 768:
        scale = 768 / shortest
        w *= scale
        h *= scale

    tiles = ceil(w / 512) * ceil(h / 512)
    return base + tile * tiles


def estimate_claude_image_tokens(width: int, height: int) -> int:
    """Anthropic approximate: tokens ≈ (width * height) / 750."""
    if width <= 0 or height <= 0:
        return 0
    return max(1, (width * height) // 750)


def estimate_gemini_image_tokens(width: int, height: int) -> int:
    """Rough Gemini 1.5 image token estimate."""
    if width <= 0 or height <= 0:
        return 0
    if width <= 384 and height <= 384:
        return 258
    tiles_w = ceil(width / 768)
    tiles_h = ceil(height / 768)
    return 258 * tiles_w * tiles_h


def estimate_vision_image_tokens(width: int, height: int, model_id: str) -> int:
    """Provider-aware image token estimate for plan metering."""
    if model_id.startswith("anthropic/"):
        return estimate_claude_image_tokens(width, height)
    if model_id.startswith("google/"):
        return estimate_gemini_image_tokens(width, height)
    return estimate_openai_image_tokens(width, height, model_id)
