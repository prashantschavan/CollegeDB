"""Supabase (Postgres + Storage) access. Every data query is scoped to one user."""
import mimetypes
from datetime import datetime, timezone

from supabase import Client, create_client

from .config import settings

_sb: Client | None = None

MESSAGE_COLS = ("id,user_id,client_id,content_kind,shared_title,text_content,urls,media_path,media_mime,"
                "filename,size_bytes,status,error,received_at")


def sb() -> Client:
    global _sb
    if _sb is None:
        _sb = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
    return _sb


# ---------- users ----------
def create_user(email: str, name: str, password_hash: str) -> str:
    row = {"email": email, "name": name, "password_hash": password_hash}
    return sb().table("users").insert(row).execute().data[0]["id"]


def find_user_by_email(email: str) -> dict | None:
    res = sb().table("users").select("*").eq("email", email).limit(1).execute()
    return res.data[0] if res.data else None


def get_user(user_id: str) -> dict | None:
    res = sb().table("users").select("id,email,name,created_at").eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def set_password(user_id: str, password_hash: str) -> None:
    sb().table("users").update({"password_hash": password_hash}).eq("id", user_id).execute()


# ---------- messages (raw shares) ----------
def find_by_client_id(user_id: str, client_id: str) -> dict | None:
    res = (sb().table("messages").select(MESSAGE_COLS).eq("user_id", user_id)
           .eq("client_id", client_id).limit(1).execute())
    return res.data[0] if res.data else None


def insert_message(row: dict) -> str:
    return sb().table("messages").insert(row).execute().data[0]["id"]


def update_message(message_id: str, fields: dict) -> None:
    sb().table("messages").update(fields).eq("id", message_id).execute()


def get_message(message_id: str, user_id: str | None = None) -> dict | None:
    """With user_id: only returns the message if it belongs to that user."""
    q = sb().table("messages").select(MESSAGE_COLS).eq("id", message_id)
    if user_id:
        q = q.eq("user_id", user_id)
    res = q.limit(1).execute()
    return res.data[0] if res.data else None


def list_messages(user_id: str, status: list[str], limit: int = 50) -> list[dict]:
    return (sb().table("messages").select(MESSAGE_COLS).eq("user_id", user_id).in_("status", status)
            .order("received_at", desc=True).limit(limit).execute().data)


def delete_message(message_id: str, user_id: str) -> None:
    msg = get_message(message_id, user_id)
    if not msg:
        return
    if msg.get("media_path"):
        try:
            sb().storage.from_(settings.SUPABASE_BUCKET).remove([msg["media_path"]])
        except Exception:
            pass
    sb().table("messages").delete().eq("id", message_id).eq("user_id", user_id).execute()  # items cascade


# ---------- items (structured records) ----------
def insert_item(row: dict) -> str:
    return sb().table("items").insert(row).execute().data[0]["id"]


def delete_items_for(message_id: str) -> None:
    sb().table("items").delete().eq("message_id", message_id).execute()


def item_for_message(message_id: str, user_id: str) -> dict | None:
    res = (sb().table("items_full").select("*").eq("message_id", message_id)
           .eq("user_id", user_id).limit(1).execute())
    return _clean(res.data[0]) if res.data else None


def search_items(user_id: str, q: str = "", category: str = "", upcoming: bool = False, limit: int = 50) -> list[dict]:
    res = sb().rpc("search_items", {"uid": user_id, "q": q or None, "cat": category or None,
                                    "upcoming": upcoming, "lim": limit}).execute()
    return [_clean(r) for r in res.data or []]


def _clean(row: dict) -> dict:
    row.pop("search", None)
    return row


# ---------- storage (original files) ----------
def upload_media(user_id: str, key: str, data: bytes, mime: str, filename: str | None = None) -> str:
    if filename and "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()[:8]
    else:
        ext = mimetypes.guess_extension((mime or "").split(";")[0].strip()) or ""
    now = datetime.now(timezone.utc)
    path = f"{user_id}/{now:%Y/%m}/{key}{ext}"
    sb().storage.from_(settings.SUPABASE_BUCKET).upload(
        path, data, file_options={"content-type": mime or "application/octet-stream", "upsert": "true"}
    )
    return path


def download_media(path: str) -> bytes:
    return sb().storage.from_(settings.SUPABASE_BUCKET).download(path)


def signed_url(path: str, seconds: int = 3600) -> str:
    res = sb().storage.from_(settings.SUPABASE_BUCKET).create_signed_url(path, seconds)
    return res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
