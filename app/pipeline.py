"""Read a saved share with Gemini and store the structured record. Also used for 'Retry'."""
import logging
from datetime import datetime

from . import classifier as C
from . import db
from .extractors import image_blocks, link_blocks, pdf_blocks, youtube_blocks, youtube_info
from .structurer import NoApiKey, structure

log = logging.getLogger(__name__)


def process_message(message_id: str, data: bytes | None = None, api_key: str | None = None) -> None:
    msg = db.get_message(message_id)
    if not msg:
        return
    kind = msg["content_kind"]
    text = msg.get("text_content") or ""
    if msg.get("shared_title"):
        text = f"(Shared title: {msg['shared_title']})\n{text}".strip()

    try:
        if kind in C.FILE_KINDS and data is None and msg.get("media_path"):
            data = db.download_media(msg["media_path"])

        blocks, source_meta = _extract(kind, text, data, msg)
        if blocks is None:  # audio/video/docx: kept, not read (later phase)
            db.update_message(message_id, {"status": "stored", "error": None})
            return

        result = structure(blocks, api_key)
        db.delete_items_for(message_id)  # makes Retry idempotent
        db.insert_item({
            "message_id": message_id,
            "category": result.get("category"),
            "title": result.get("title"),
            "summary": result.get("summary"),
            "issuing_authority": result.get("issuing_authority"),
            "reference_no": result.get("reference_no"),
            "issue_date": _date(result.get("issue_date")),
            "deadline": _date(result.get("deadline")),
            "key_dates": result.get("key_dates") or [],
            "action_items": result.get("action_items") or [],
            "people": result.get("people") or [],
            "departments": result.get("departments") or [],
            "tags": [t.lower() for t in result.get("tags") or []],
            "language": result.get("language"),
            "confidence": result.get("confidence"),
            "source_url": source_meta.get("url"),
            "source_meta": source_meta,
        })
        db.update_message(message_id, {"status": "processed", "error": None})
        log.info("Processed %s (%s)", message_id, kind)
    except Exception as e:
        log.exception("Processing %s failed", message_id)
        db.update_message(message_id, {"status": "failed", "error": friendly_error(e)[:2000]})


def _extract(kind: str, text: str, data: bytes | None, msg: dict):
    """Returns (claude_blocks | None, source_meta)."""
    urls = C.find_urls(text)
    if kind == C.TEXT:
        return [{"type": "text", "text": f"A text message was shared from WhatsApp:\n\n{text}"}], {}

    if kind == C.YOUTUBE:
        info = youtube_info(C.youtube_id(urls[0]), urls[0])
        meta = {k: v for k, v in info.items() if k != "transcript"}
        meta["has_transcript"] = bool(info.get("transcript"))
        return youtube_blocks(info, text), meta

    if kind == C.LINK:
        blocks, meta = link_blocks(urls[0], text)
        if len(urls) > 1:
            meta["other_urls"] = urls[1:]
        return blocks, meta

    meta = {"mime": msg.get("media_mime"), "filename": msg.get("filename"), "size_bytes": msg.get("size_bytes")}
    if kind == C.IMAGE:
        return image_blocks(data, msg.get("media_mime") or "image/jpeg", text), meta
    if kind == C.PDF:
        return pdf_blocks(data, msg.get("filename") or "", text), meta
    return None, meta


def _date(s):
    """Keep only valid YYYY-MM-DD strings so Postgres DATE columns never reject the row."""
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def friendly_error(e: Exception) -> str:
    """Turn common Gemini errors into something a student can act on."""
    msg = str(e)
    if isinstance(e, NoApiKey):
        return msg
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "Free Gemini limit reached for now. Wait a minute (or until tomorrow), then tap Retry."
    if "API_KEY_INVALID" in msg or "API key not valid" in msg or "PERMISSION_DENIED" in msg:
        return "Your Gemini API key was rejected. Check it in Settings, then tap Retry."
    if "503" in msg or "UNAVAILABLE" in msg or "overloaded" in msg.lower():
        return "Gemini is busy right now. Tap Retry in a minute."
    return msg
