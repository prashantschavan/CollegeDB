"""Use Google Gemini (free tier) to turn extracted content into a fixed JSON record."""
import base64
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from .config import settings

CATEGORIES = [
    "exam", "circular", "notice", "meeting", "event", "admission", "result", "timetable",
    "holiday", "deadline", "job", "training", "video", "article", "news", "document",
    "personal", "other",
]

# Plain JSON Schema. Unknown values come back as "" (or []) and are cleaned up afterwards.
SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "title": {"type": "string", "description": "Short, specific English title, max ~12 words"},
        "summary": {"type": "string", "description": "2-4 sentence English summary of what matters"},
        "issuing_authority": {"type": "string", "description": "Office/organisation/person that issued it, or empty"},
        "reference_no": {"type": "string", "description": "Circular/notice/letter number, or empty"},
        "issue_date": {"type": "string", "description": "YYYY-MM-DD or empty"},
        "deadline": {"type": "string", "description": "Most important upcoming deadline YYYY-MM-DD, or empty"},
        "key_dates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                    "time": {"type": "string", "description": "HH:MM 24h, or empty"},
                },
                "required": ["label", "date"],
            },
        },
        "action_items": {"type": "array", "items": {"type": "string"}},
        "people": {"type": "array", "items": {"type": "string"}},
        "departments": {"type": "array", "items": {"type": "string"}},
        "tags": {"type": "array", "items": {"type": "string"}, "description": "3-8 lowercase topic tags"},
        "language": {"type": "string"},
        "confidence": {"type": "number", "description": "0-1 how readable/complete the source was"},
    },
    "required": ["category", "title", "summary", "tags", "key_dates", "action_items"],
}

SYSTEM_PROMPT = """You extract structured records from content a user shares (mostly from WhatsApp) into their personal database.
Users are students and faculty of engineering colleges in India, so expect college notices, university circulars,
AICTE/UGC/government letters, exam schedules, results, placement/job posts, events, and educational videos/articles.

Rules:
- Today's date is {today} ({tz}). Resolve relative dates ("tomorrow", "next Monday") against it.
- Indian dates are usually DD/MM/YYYY. Output all dates as YYYY-MM-DD.
- Content may be in Marathi, Hindi or English. Write title/summary/tags in English; keep proper names as written.
- Only record what is actually present. Never invent dates, numbers or authorities; use "" or [] instead.
- For videos/articles, the summary should say what it teaches or is about."""


FALLBACK_MODEL = "gemini-3.8-flash"
_active_model: str | None = None   # set when the configured model turned out to be retired


def _replacement_model(error: str, current: str) -> str | None:
    if "NOT_FOUND" not in error and "404" not in error:
        return None
    m = re.search(r"use models/([A-Za-z0-9.\-]+)", error)
    candidate = m.group(1).rstrip(".") if m else FALLBACK_MODEL
    return candidate if candidate != current else None


class NoApiKey(Exception):
    pass


def _parts(blocks: list[dict]) -> list:
    """Convert the pipeline's neutral content blocks into Gemini parts."""
    parts = []
    for b in blocks:
        if b["type"] == "text":
            parts.append(b["text"])
        elif b["type"] in ("image", "document"):
            src = b["source"]
            parts.append(types.Part.from_bytes(data=base64.b64decode(src["data"]), mime_type=src["media_type"]))
    return parts


def structure(blocks: list[dict], api_key: str | None = None) -> dict:
    key = api_key or (settings.GEMINI_API_KEY if settings.ALLOW_SHARED_KEY else "")
    if not key:
        raise NoApiKey("No Gemini API key. Add your free key in the app: Settings → Gemini API key.")
    now = datetime.now(ZoneInfo(settings.TIMEZONE))
    client = genai.Client(api_key=key)
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(today=now.strftime("%Y-%m-%d (%A)"), tz=settings.TIMEZONE),
        response_mime_type="application/json",
        response_json_schema=SCHEMA,
        temperature=0.1,
    )
    contents = _parts(blocks)
    global _active_model
    model = _active_model or settings.GEMINI_MODEL
    try:
        resp = client.models.generate_content(model=model, contents=contents, config=config)
    except Exception as e:
        # Google retires older models for new users ("404 NOT_FOUND ... no longer available ... use models/X").
        # Switch to the model Google names (or our fallback) and remember it for later requests.
        replacement = _replacement_model(str(e), model)
        if not replacement:
            raise
        resp = client.models.generate_content(model=replacement, contents=contents, config=config)
        _active_model = replacement
    if not resp.text:
        raise RuntimeError("Gemini returned no content (it may have been blocked by safety filters)")
    return _clean(json.loads(resp.text))


def _clean(d: dict) -> dict:
    """Empty strings -> None; normalise category and tags."""
    out = {k: (None if v == "" else v) for k, v in d.items()}
    if out.get("category") not in CATEGORIES:
        out["category"] = "other"
    out["key_dates"] = [{**kd, "time": kd.get("time") or None} for kd in out.get("key_dates") or [] if kd.get("date")]
    out["tags"] = [t.strip().lower() for t in out.get("tags") or [] if t and t.strip()]
    return out
