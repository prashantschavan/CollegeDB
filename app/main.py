"""FastAPI server: serves the installable app (PWA), accounts, and the per-user API."""
import hmac
import logging
import re
from pathlib import Path

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, db
from . import classifier as C
from .config import settings
from .pipeline import process_message
from .structurer import CATEGORIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("my-saver")

STATIC = Path(__file__).parent / "static"
NO_CACHE = {"Cache-Control": "no-cache"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

app = FastAPI(title="My Saver")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---------------- app shell ----------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript",
                        headers={**NO_CACHE, "Service-Worker-Allowed": "/"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json", headers=NO_CACHE)


@app.post("/share-target", include_in_schema=False)
def share_target_fallback():
    """Normally the service worker catches shares before they reach here."""
    return RedirectResponse("/?share_missed=1", status_code=303)


@app.get("/health")
def health():
    return {"ok": True}


# ---------------- accounts ----------------
def current_user(authorization: str = Header("")) -> str:
    user_id = auth.read_token(authorization.removeprefix("Bearer ").strip())
    if not user_id:
        raise HTTPException(401, "Please log in again")
    return user_id


@app.get("/api/config")
def public_config():
    return {"class_code_required": bool(settings.CLASS_CODE),
            "shared_key_available": bool(settings.ALLOW_SHARED_KEY and settings.GEMINI_API_KEY)}


@app.post("/api/auth/register")
def register(name: str = Body(...), email: str = Body(...), password: str = Body(...), class_code: str = Body("")):
    email = email.strip().lower()
    if settings.CLASS_CODE and not hmac.compare_digest(class_code.strip(), settings.CLASS_CODE):
        raise HTTPException(403, "Wrong class code. Ask your teacher for it.")
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address")
    if len(password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    if not name.strip():
        raise HTTPException(400, "Enter your name")
    if db.find_user_by_email(email):
        raise HTTPException(409, "An account with this email already exists. Log in instead.")
    user_id = db.create_user(email, name.strip()[:80], auth.hash_password(password))
    return {"token": auth.make_token(user_id), "name": name.strip()}


@app.post("/api/auth/login")
def login(email: str = Body(...), password: str = Body(...)):
    user = db.find_user_by_email(email.strip().lower())
    if not user or not auth.check_password(password, user["password_hash"]):
        raise HTTPException(401, "Wrong email or password")
    return {"token": auth.make_token(user["id"]), "name": user["name"]}


@app.get("/api/me")
def me(user_id: str = Depends(current_user)):
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(401, "Account not found. Please sign up again.")
    return user


@app.post("/api/me/password")
def change_password(old_password: str = Body(...), new_password: str = Body(...),
                    user_id: str = Depends(current_user)):
    user = db.find_user_by_email(db.get_user(user_id)["email"])
    if not auth.check_password(old_password, user["password_hash"]):
        raise HTTPException(403, "Current password is wrong")
    if len(new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    db.set_password(user_id, auth.hash_password(new_password))
    return {"ok": True}


# ---------------- saving shares ----------------
def gemini_key(x_gemini_key: str = Header("")) -> str | None:
    """Each user's own free Gemini key travels with the request; it is never stored on the server."""
    return x_gemini_key.strip() or None


@app.post("/api/ingest")
def ingest(
    background: BackgroundTasks,
    client_id: str = Form(...),
    text: str = Form(""),
    title: str = Form(""),
    url: str = Form(""),
    file: UploadFile | None = File(None),
    user_id: str = Depends(current_user),
    api_key: str | None = Depends(gemini_key),
):
    existing = db.find_by_client_id(user_id, client_id)
    if existing:  # phone retried an upload that already arrived
        return {"id": existing["id"], "status": existing["status"], "kind": existing["content_kind"]}

    full_text = C.merge_text(text, url)
    data, mime, filename = None, None, None
    if file is not None and file.filename is not None:
        data = file.file.read()
        mime = file.content_type or "application/octet-stream"
        filename = file.filename
        if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"File is larger than {settings.MAX_UPLOAD_MB} MB")
        if not data:
            data, mime, filename = None, None, None
    if not data and not full_text:
        raise HTTPException(400, "Nothing to save")

    kind = C.classify(full_text, mime, filename) if data else C.classify(full_text)
    message_id = db.insert_message({
        "user_id": user_id,
        "client_id": client_id,
        "content_kind": kind,
        "shared_title": title.strip() or None,
        "text_content": full_text or None,
        "urls": C.find_urls(full_text),
        "media_mime": mime,
        "filename": filename,
        "size_bytes": len(data) if data else None,
        "status": "processing",
    })
    if data:
        db.update_message(message_id, {"media_path": db.upload_media(user_id, message_id, data, mime, filename)})

    background.add_task(process_message, message_id, data, api_key)
    return {"id": message_id, "status": "processing", "kind": kind}


@app.get("/api/messages/{message_id}")
def message_status(message_id: str, user_id: str = Depends(current_user)):
    msg = db.get_message(message_id, user_id)
    if not msg:
        raise HTTPException(404, "Not found")
    item = db.item_for_message(message_id, user_id) if msg["status"] == "processed" else None
    return {"message": msg, "item": item}


@app.get("/api/messages")
def messages(status: str = Query("failed,stored,processing"), user_id: str = Depends(current_user)):
    return db.list_messages(user_id, [s.strip() for s in status.split(",") if s.strip()])


@app.post("/api/messages/{message_id}/retry")
def retry(message_id: str, background: BackgroundTasks, user_id: str = Depends(current_user),
          api_key: str | None = Depends(gemini_key)):
    if not db.get_message(message_id, user_id):
        raise HTTPException(404, "Not found")
    db.update_message(message_id, {"status": "processing", "error": None})
    background.add_task(process_message, message_id, None, api_key)
    return {"id": message_id, "status": "processing"}


@app.delete("/api/messages/{message_id}")
def delete(message_id: str, user_id: str = Depends(current_user)):
    db.delete_message(message_id, user_id)
    return {"deleted": message_id}


@app.get("/api/items")
def items(q: str = "", category: str = "", upcoming: bool = False, limit: int = Query(50, le=200),
          user_id: str = Depends(current_user)):
    return db.search_items(user_id, q, category, upcoming, limit)


@app.get("/api/file/{message_id}")
def original_file(message_id: str, user_id: str = Depends(current_user)):
    msg = db.get_message(message_id, user_id)
    if not msg or not msg.get("media_path"):
        raise HTTPException(404, "No file for this item")
    return {"url": db.signed_url(msg["media_path"]), "filename": msg.get("filename")}


@app.get("/api/categories")
def categories():
    return CATEGORIES
