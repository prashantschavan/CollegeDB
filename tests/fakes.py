"""In-memory stand-ins for Supabase and Claude, used by the tests and the demo server."""
import uuid
from datetime import date, datetime, timezone

from app import db, main, pipeline


class FakeDB:
    def __init__(self):
        self.users: dict[str, dict] = {}
        self.messages: dict[str, dict] = {}
        self.items: dict[str, dict] = {}
        self.files: dict[str, bytes] = {}

    # users
    def create_user(self, email, name, password_hash):
        uid = str(uuid.uuid4())
        self.users[uid] = {"id": uid, "email": email, "name": name, "password_hash": password_hash}
        return uid

    def find_user_by_email(self, email):
        return next((u for u in self.users.values() if u["email"] == email), None)

    def get_user(self, uid):
        u = self.users.get(uid)
        return {k: v for k, v in u.items() if k != "password_hash"} if u else None

    def set_password(self, uid, h):
        self.users[uid]["password_hash"] = h

    # messages
    def find_by_client_id(self, uid, cid):
        return next((m for m in self.messages.values() if m["client_id"] == cid and m["user_id"] == uid), None)

    def insert_message(self, row):
        mid = str(uuid.uuid4())
        self.messages[mid] = {"id": mid, "status": "processing", "error": None, "media_path": None,
                              "received_at": datetime.now(timezone.utc).isoformat(), **row}
        return mid

    def update_message(self, mid, fields):
        self.messages[mid].update(fields)

    def get_message(self, mid, uid=None):
        m = self.messages.get(mid)
        return m if m and (uid is None or m["user_id"] == uid) else None

    def list_messages(self, uid, status, limit=50):
        return [m for m in self.messages.values() if m["status"] in status and m["user_id"] == uid][:limit]

    def delete_message(self, mid, uid):
        if not self.get_message(mid, uid):
            return
        self.messages.pop(mid, None)
        for k in [k for k, v in self.items.items() if v["message_id"] == mid]:
            self.items.pop(k)

    def insert_item(self, row):
        iid = str(uuid.uuid4())
        self.items[iid] = {"id": iid, "created_at": datetime.now(timezone.utc).isoformat(), **row}
        return iid

    def delete_items_for(self, mid):
        for k in [k for k, v in self.items.items() if v["message_id"] == mid]:
            self.items.pop(k)

    def _full(self, it):
        m = self.messages[it["message_id"]]
        return {**it, "user_id": m["user_id"], "content_kind": m["content_kind"], "media_path": m.get("media_path"),
                "filename": m.get("filename"), "text_content": m.get("text_content")}

    def item_for_message(self, mid, uid):
        it = next((v for v in self.items.values() if v["message_id"] == mid), None)
        return self._full(it) if it and self.messages[mid]["user_id"] == uid else None

    def search_items(self, uid, q="", category="", upcoming=False, limit=50):
        out = [self._full(i) for i in self.items.values()]
        out = [i for i in out if i["user_id"] == uid]
        if q:
            ql = q.lower()
            out = [i for i in out if ql in (i["title"] + " " + i["summary"] + " " + " ".join(i["tags"])).lower()]
        if category:
            out = [i for i in out if i["category"] == category]
        if upcoming:
            today = date.today().isoformat()
            out = sorted([i for i in out if i.get("deadline") and i["deadline"] >= today], key=lambda i: i["deadline"])
        else:
            out.sort(key=lambda i: i["created_at"], reverse=True)
        return out[:limit]

    def upload_media(self, uid, key, data, mime, filename=None):
        path = f"{uid}/2026/10/{key}"
        self.files[path] = data
        return path

    def download_media(self, path):
        return self.files[path]

    def signed_url(self, path, seconds=3600):
        return f"https://example.supabase.co/signed/{path}"


FAKE_CALLS: list = []


def fake_structure(blocks, api_key=None):
    """Pretends to be Gemini: derives a record from what it was given."""
    FAKE_CALLS.append(api_key)
    kinds = [b["type"] for b in blocks]
    text = " ".join(b.get("text", "") for b in blocks if b["type"] == "text")
    if "image" in kinds:
        return {"category": "exam", "title": "End-semester exam form submission", "summary": "Students must submit exam forms online.",
                "issuing_authority": "Exam Cell, BVDU COE", "reference_no": "BVDU/EX/2026/114", "issue_date": "2026-10-01",
                "deadline": "2026-10-06", "key_dates": [{"label": "Last date for form", "date": "2026-10-06"},
                                                         {"label": "Late fee window ends", "date": "2026-10-09"}],
                "action_items": ["Fill form on portal", "Pay fee"], "tags": ["exam", "form", "deadline"], "language": "English"}
    if "FAIL" in text:
        raise RuntimeError("Simulated Claude error")
    return {"category": "meeting", "title": "Department meeting on NBA accreditation", "summary": text[-120:],
            "deadline": None, "key_dates": [], "action_items": [], "tags": ["meeting", "nba"], "language": "English"}


def install(monkeypatch=None):
    """Patch app modules to use the fakes. Works with pytest's monkeypatch or plain setattr."""
    fake = FakeDB()
    setter = monkeypatch.setattr if monkeypatch else setattr
    for name in [n for n in dir(FakeDB) if not n.startswith("_")]:
        setter(db, name, getattr(fake, name))
    setter(pipeline, "structure", fake_structure)
    setter(main.settings, "SECRET_KEY", "test-secret")
    setter(main.settings, "CLASS_CODE", "BVDU26")
    return fake
