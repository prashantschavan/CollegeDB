"""Decide what kind of content was shared into the app."""
import re

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
YT_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})",
    re.IGNORECASE,
)

TEXT, LINK, YOUTUBE, IMAGE, PDF, DOCUMENT, AUDIO, VIDEO = (
    "text", "link", "youtube", "image", "pdf", "document", "audio", "video",
)
FILE_KINDS = {IMAGE, PDF, DOCUMENT, AUDIO, VIDEO}


def find_urls(text: str | None) -> list[str]:
    if not text:
        return []
    return [u.rstrip(".,);]}>") for u in URL_RE.findall(text)]


def youtube_id(url: str) -> str | None:
    m = YT_RE.search(url)
    return m.group(1) if m else None


def merge_text(text: str = "", url: str = "") -> str:
    """Android puts shared content in 'text' and sometimes repeats the link in 'url'."""
    text = (text or "").strip()
    url = (url or "").strip()
    if url and url not in text:
        text = f"{text}\n{url}".strip()
    return text


def classify(text: str = "", mime: str | None = None, filename: str | None = None) -> str:
    if mime or filename:
        mime = (mime or "").lower()
        name = (filename or "").lower()
        if mime.startswith("image/"):
            return IMAGE
        if mime == "application/pdf" or name.endswith(".pdf"):
            return PDF
        if mime.startswith("audio/") or name.endswith((".opus", ".ogg", ".mp3", ".m4a", ".aac")):
            return AUDIO
        if mime.startswith("video/"):
            return VIDEO
        return DOCUMENT
    urls = find_urls(text)
    if not urls:
        return TEXT
    return YOUTUBE if youtube_id(urls[0]) else LINK
