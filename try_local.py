"""Test the extraction on your own files/links BEFORE setting up WhatsApp or Supabase.
Only GEMINI_API_KEY is needed in .env (free key from aistudio.google.com/apikey).

    python try_local.py notice.jpg
    python try_local.py circular.pdf
    python try_local.py "https://youtu.be/VIDEO_ID"
    python try_local.py "https://some-site/notice"
    python try_local.py "Staff meeting tomorrow at 3 pm in Seminar Hall"
"""
import json
import mimetypes
import os
import sys
from pathlib import Path

from app import classifier as C
from app.extractors import image_blocks, link_blocks, pdf_blocks, youtube_blocks, youtube_info
from app.structurer import structure


def main(arg: str):
    p = Path(arg)
    if p.is_file():
        data = p.read_bytes()
        mime = mimetypes.guess_type(p.name)[0] or ""
        if mime == "application/pdf":
            blocks = pdf_blocks(data, p.name)
        elif mime.startswith("image/"):
            blocks = image_blocks(data, mime)
        else:
            sys.exit(f"Unsupported file type: {mime}")
    else:
        urls = C.find_urls(arg)
        if urls and C.youtube_id(urls[0]):
            info = youtube_info(C.youtube_id(urls[0]), urls[0])
            print("YouTube metadata:", json.dumps({k: v for k, v in info.items() if k != "transcript"}, indent=2))
            blocks = youtube_blocks(info, arg)
        elif urls:
            blocks, meta = link_blocks(urls[0], arg)
            print("Page metadata:", json.dumps(meta, indent=2))
        else:
            blocks = [{"type": "text", "text": f"A text message was forwarded from WhatsApp:\n\n{arg}"}]

    print("\nExtracted record:")
    print(json.dumps(structure(blocks, os.getenv("GEMINI_API_KEY")), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1])
