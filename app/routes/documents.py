from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings
from app.services.pdf import estimate_pdf_tokens, parse_pdf

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/parse-pdf")
async def parse_pdf_upload(file: UploadFile = File(...)):
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    if len(data) > settings.max_pdf_upload_bytes:
        max_mb = settings.max_pdf_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"PDF exceeds {max_mb}MB limit")

    try:
        text, page_count = parse_pdf(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {exc}") from exc

    if not text.strip():
        raise HTTPException(
            status_code=400,
            detail="No text could be extracted from this PDF. It may be scanned or image-only.",
        )

    return {
        "filename": filename,
        "text": text,
        "page_count": page_count,
        "char_count": len(text),
        "token_estimate": estimate_pdf_tokens(text),
    }
