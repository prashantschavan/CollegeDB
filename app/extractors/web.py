"""Fetch a generic web link and pull out its readable content."""
import logging

import httpx
from bs4 import BeautifulSoup

from .media import pdf_blocks

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def link_blocks(url: str, message_text: str) -> tuple[list[dict], dict]:
    """Returns (claude_blocks, page_meta). Links that point to a PDF are read as PDFs."""
    meta = {"url": url}
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
        r.raise_for_status()
        meta["final_url"] = str(r.url)
        ctype = r.headers.get("content-type", "").lower()
        if "application/pdf" in ctype or str(r.url).lower().endswith(".pdf"):
            meta["content_type"] = "pdf"
            return pdf_blocks(r.content, filename=str(r.url).rsplit("/", 1)[-1], caption=message_text), meta
        meta.update(_parse_html(r.text))
    except Exception as e:
        log.warning("Fetching %s failed: %s", url, e)
        meta["fetch_error"] = str(e)

    parts = [f"A web link was shared from WhatsApp (or another app).\nShared text: {message_text}\nURL: {url}"]
    for k in ("page_title", "description", "site_name"):
        if meta.get(k):
            parts.append(f"{k}: {meta[k]}")
    if meta.get("body_text"):
        parts.append(f"Page content (truncated):\n{meta['body_text']}")
    if meta.get("fetch_error"):
        parts.append("(The page could not be fetched; work from the URL and message text only.)")
    return [{"type": "text", "text": "\n".join(parts)}], {k: v for k, v in meta.items() if k != "body_text"}


def _parse_html(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def og(prop):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return tag.get("content") if tag and tag.get("content") else None

    for t in soup(["script", "style", "nav", "footer", "header", "noscript", "aside"]):
        t.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = " ".join(main.get_text(" ", strip=True).split())
    return {
        "page_title": og("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else None),
        "description": og("og:description") or og("description"),
        "site_name": og("og:site_name"),
        "body_text": text[:8000],
    }
