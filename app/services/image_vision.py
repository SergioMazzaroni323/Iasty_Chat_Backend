import base64
import re
import struct

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

# Conservative fallback when dimensions cannot be parsed (≈ 1024x1024 high detail)
DEFAULT_IMAGE_SIZE = (1024, 1024)


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


def get_image_dimensions(raw: bytes) -> tuple[int, int] | None:
    """Return (width, height) from common image headers, or None if unknown."""
    if len(raw) < 24:
        return None

    # PNG
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and len(raw) >= 24:
        width, height = struct.unpack(">II", raw[16:24])
        if width > 0 and height > 0:
            return width, height

    # GIF
    if raw[:6] in (b"GIF87a", b"GIF89a") and len(raw) >= 10:
        width, height = struct.unpack("<HH", raw[6:10])
        if width > 0 and height > 0:
            return width, height

    # JPEG
    if raw[:2] == b"\xff\xd8":
        size = _jpeg_dimensions(raw)
        if size:
            return size

    # WEBP
    if raw[:4] == b"RIFF" and len(raw) >= 16 and raw[8:12] == b"WEBP":
        size = _webp_dimensions(raw)
        if size:
            return size

    return None


def _jpeg_dimensions(raw: bytes) -> tuple[int, int] | None:
    i = 2
    while i + 9 < len(raw):
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker == 0xD9:  # EOI
            break
        if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01) or marker == 0xD8:
            i += 2
            continue
        if i + 4 > len(raw):
            break
        length = struct.unpack(">H", raw[i + 2 : i + 4])[0]
        if length < 2:
            break
        # SOF0 / SOF1 / SOF2
        if marker in (0xC0, 0xC1, 0xC2) and i + 9 < len(raw):
            height, width = struct.unpack(">HH", raw[i + 5 : i + 9])
            if width > 0 and height > 0:
                return width, height
        i += 2 + length
    return None


def _webp_dimensions(raw: bytes) -> tuple[int, int] | None:
    if len(raw) < 30:
        return None
    chunk = raw[12:16]
    if chunk == b"VP8 " and len(raw) >= 30:
        width = struct.unpack("<H", raw[26:28])[0] & 0x3FFF
        height = struct.unpack("<H", raw[28:30])[0] & 0x3FFF
        if width > 0 and height > 0:
            return width, height
    if chunk == b"VP8L" and len(raw) >= 25:
        bits = struct.unpack("<I", raw[21:25])[0]
        width = (bits & 0x3FFF) + 1
        height = ((bits >> 14) & 0x3FFF) + 1
        return width, height
    if chunk == b"VP8X" and len(raw) >= 30:
        width = 1 + int.from_bytes(raw[24:27], "little")
        height = 1 + int.from_bytes(raw[27:30], "little")
        if width > 0 and height > 0:
            return width, height
    return None


def decode_image_payload(raw_base64: str, mime: str) -> tuple[str, bytes, str]:
    """Validate and return (data_url, raw_bytes, mime)."""
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

    return f"data:{mime};base64,{data}", raw, mime


def build_image_data_url(raw_base64: str, mime: str) -> str:
    data_url, _, _ = decode_image_payload(raw_base64, mime)
    return data_url


def prepare_vision_image(raw_base64: str, mime: str) -> tuple[str, int, int]:
    """Return (data_url, width, height). Falls back to 1024x1024 if unreadable."""
    data_url, raw, _ = decode_image_payload(raw_base64, mime)
    size = get_image_dimensions(raw) or DEFAULT_IMAGE_SIZE
    return data_url, size[0], size[1]


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
