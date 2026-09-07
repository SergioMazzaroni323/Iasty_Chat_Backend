import base64
import re

from app.config import settings

IMAGE_ATTACHMENT_MARKER = "\n\n---\nAttached Image ({filename}):\n[Image attached for vision analysis]"

ALLOWED_IMAGE_MIME = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
}

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def normalize_image_mime(mime: str | None, filename: str | None = None) -> str:
    cleaned = (mime or "").strip().lower()
    if cleaned == "image/jpg":
        cleaned = "image/jpeg"
    if cleaned in ALLOWED_IMAGE_MIME:
        return cleaned
    if filename:
        lower = filename.lower()
        for ext, mapped in MIME_BY_EXT.items():
            if lower.endswith(ext):
                return mapped
    raise ValueError("Unsupported image type. Use PNG, JPEG, WEBP, or GIF.")


def build_image_data_url(raw_base64: str, mime: str) -> str:
    data = raw_base64.strip()
    if data.startswith("data:"):
        match = re.match(r"^data:([^;]+);base64,(.+)$", data, flags=re.DOTALL)
        if not match:
            raise ValueError("Invalid image data URL")
        mime = normalize_image_mime(match.group(1))
        data = match.group(2).strip()
    else:
        mime = normalize_image_mime(mime)

    if not data:
        raise ValueError("Empty image data")
    if len(data) > settings.max_image_base64_chars:
        max_mb = settings.max_image_upload_bytes // (1024 * 1024)
        raise ValueError(f"Image exceeds {max_mb}MB limit")

    try:
        raw = base64.b64decode(data, validate=False)
    except Exception as exc:
        raise ValueError("Invalid image encoding") from exc

    if not raw:
        raise ValueError("Empty image data")
    if len(raw) > settings.max_image_upload_bytes:
        max_mb = settings.max_image_upload_bytes // (1024 * 1024)
        raise ValueError(f"Image exceeds {max_mb}MB limit")

    return f"data:{mime};base64,{data}"


def format_image_message_for_storage(content: str, filename: str) -> str:
    base = content.strip()
    attachment = IMAGE_ATTACHMENT_MARKER.format(filename=filename)
    return f"{base}{attachment}" if base else attachment.lstrip("\n")


def build_vision_user_content(
    text: str,
    image_data_url: str,
    filename: str | None = None,
) -> list[dict]:
    prompt = text.strip() or (
        f'Please analyze the attached image{f" named {filename}" if filename else ""} and describe anything important.'
    )
    return [
        {"type": "text", "text": prompt},
        {
            "type": "image_url",
            "image_url": {"url": image_data_url, "detail": "auto"},
        },
    ]


def replace_last_user_message_with_vision(
    messages: list[dict],
    vision_content: list[dict],
) -> list[dict]:
    updated = list(messages)
    for i in range(len(updated) - 1, -1, -1):
        if updated[i].get("role") == "user":
            updated[i] = {"role": "user", "content": vision_content}
            return updated
    updated.append({"role": "user", "content": vision_content})
    return updated
