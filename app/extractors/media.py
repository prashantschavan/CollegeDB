"""Turn images and PDFs into content blocks that the AI model reads directly (no separate OCR)."""
import base64
import io

from pypdf import PdfReader

IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_PDF_BYTES = 18 * 1024 * 1024  # Gemini inline requests are limited to 20 MB


def image_blocks(data: bytes, mime: str, caption: str = "") -> list[dict]:
    mime = mime.split(";")[0].strip().lower()
    if mime not in IMAGE_TYPES:
        mime = "image/jpeg"  # WhatsApp images are almost always JPEG
    blocks = [{
        "type": "image",
        "source": {"type": "base64", "media_type": mime, "data": base64.b64encode(data).decode()},
    }]
    blocks.append({"type": "text", "text": _caption_note(caption) + "This is an image shared from WhatsApp (or another app) (often a photo or screenshot of an official notice). Read all text in it, including Marathi/Hindi."})
    return blocks


def pdf_blocks(data: bytes, filename: str = "", caption: str = "") -> list[dict]:
    """Send the PDF itself (works for scanned PDFs too). Very large files fall back to text extraction."""
    note = _caption_note(caption) + f"This is a PDF document shared from WhatsApp (or another app) (filename: {filename or 'unknown'})."
    if len(data) <= MAX_PDF_BYTES:
        return [
            {"type": "document",
             "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(data).decode()}},
            {"type": "text", "text": note},
        ]
    return [{"type": "text", "text": note + "\n\nExtracted text (file too large to attach):\n" + pdf_text(data)[:60000]}]


def pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as e:
        return f"[could not extract PDF text: {e}]"


def _caption_note(caption: str) -> str:
    return f"Text shared along with it: {caption}\n\n" if caption else ""
