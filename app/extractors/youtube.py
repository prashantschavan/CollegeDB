"""YouTube metadata (+ optional transcript) for a video link."""
import logging

import httpx

from ..config import settings

log = logging.getLogger(__name__)


def youtube_info(video_id: str, url: str) -> dict:
    info = {"video_id": video_id, "url": f"https://www.youtube.com/watch?v={video_id}", "original_url": url}
    try:
        if settings.YOUTUBE_API_KEY:
            info.update(_data_api(video_id))
        else:
            info.update(_oembed(info["url"]))
    except Exception as e:
        log.warning("YouTube metadata failed for %s: %s", video_id, e)
    if settings.FETCH_TRANSCRIPTS:
        info["transcript"] = _transcript(video_id)
    return info


def _data_api(video_id: str) -> dict:
    r = httpx.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={"part": "snippet,contentDetails", "id": video_id, "key": settings.YOUTUBE_API_KEY},
        timeout=15,
    )
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return {}
    sn, cd = items[0]["snippet"], items[0]["contentDetails"]
    return {
        "title": sn.get("title"),
        "channel": sn.get("channelTitle"),
        "published_at": sn.get("publishedAt"),
        "description": (sn.get("description") or "")[:3000],
        "duration": cd.get("duration"),  # ISO 8601, e.g. PT12M5S
        "thumbnail": (sn.get("thumbnails", {}).get("high") or {}).get("url"),
    }


def _oembed(watch_url: str) -> dict:
    """No API key needed; gives title + channel only."""
    r = httpx.get("https://www.youtube.com/oembed", params={"url": watch_url, "format": "json"}, timeout=15)
    r.raise_for_status()
    d = r.json()
    return {"title": d.get("title"), "channel": d.get("author_name"), "thumbnail": d.get("thumbnail_url")}


def _transcript(video_id: str, limit: int = 15000) -> str | None:
    """Best effort. YouTube often blocks transcript requests from cloud servers; that's fine."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["en", "en-IN", "hi", "mr"])
        return " ".join(s.text for s in fetched)[:limit]
    except Exception as e:
        log.info("No transcript for %s: %s", video_id, e)
        return None


def youtube_blocks(info: dict, message_text: str) -> list[dict]:
    parts = [f"A YouTube video link was shared from WhatsApp (or another app).\nShared text: {message_text}"]
    for k in ("title", "channel", "published_at", "duration", "description"):
        if info.get(k):
            parts.append(f"{k}: {info[k]}")
    if info.get("transcript"):
        parts.append(f"Transcript (partial):\n{info['transcript']}")
    return [{"type": "text", "text": "\n".join(parts)}]
