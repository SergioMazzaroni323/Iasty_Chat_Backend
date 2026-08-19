from io import BytesIO

from pypdf import PdfReader

from app.config import settings
from app.services.tokens import count_tokens

ATTACHMENT_MARKER = "\n\n---\nAttached PDF ({filename}):\n"


def parse_pdf(data: bytes) -> tuple[str, int]:
    reader = PdfReader(BytesIO(data))
    page_count = len(reader.pages)
    if page_count > settings.max_pdf_pages:
        raise ValueError(f"PDF exceeds the {settings.max_pdf_pages}-page limit")

    parts: list[str] = []
    for page in reader.pages[: settings.max_pdf_pages]:
        parts.append(page.extract_text() or "")

    text = "\n\n".join(parts).strip()
    if not text:
        return "", page_count

    if len(text) > settings.max_pdf_text_chars:
        text = text[: settings.max_pdf_text_chars] + "\n\n[Truncated due to length limit]"

    return text, page_count


def build_document_context(filename: str, text: str) -> str:
    return (
        f'The user attached a PDF named "{filename}". Use its contents to answer their question.\n\n'
        f"Document contents:\n{text}"
    )


def format_user_message_for_storage(
    content: str,
    filename: str | None,
    document_text: str | None,
) -> str:
    base = content.strip()
    if not document_text or not filename:
        return base
    attachment = ATTACHMENT_MARKER.format(filename=filename) + document_text
    return f"{base}{attachment}" if base else attachment.lstrip("\n")


def split_user_message_content(content: str) -> tuple[str, str | None]:
    marker = "\n\n---\nAttached PDF ("
    idx = content.find(marker)
    if idx == -1:
        return content, None

    text = content[:idx].rstrip()
    rest = content[idx + len(marker) :]
    end = rest.find("):\n")
    if end == -1:
        return content, None

    filename = rest[:end]
    return text, filename


def estimate_pdf_tokens(text: str) -> int:
    return count_tokens(text)
