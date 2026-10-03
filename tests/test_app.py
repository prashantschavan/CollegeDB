"""Offline tests - no Gemini or Supabase calls are made."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

from app import auth, main, pipeline, structurer
from app import classifier as C
from tests import fakes


@pytest.fixture
def env(monkeypatch):
    fakes.FAKE_CALLS.clear()
    fake = fakes.install(monkeypatch)
    return fake, TestClient(main.app)


def signup(client, email="asha@bvucoep.edu.in", name="Asha", code="BVDU26", password="secret123"):
    r = client.post("/api/auth/register", json={"name": name, "email": email, "password": password, "class_code": code})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", "X-Gemini-Key": f"key-of-{name}"}


# ---------------- classifier ----------------
def test_classify_variants():
    assert C.classify("Meeting at 4 pm in seminar hall") == C.TEXT
    assert C.classify("Watch https://youtu.be/dQw4w9WgXcQ") == C.YOUTUBE
    assert C.classify("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s") == C.YOUTUBE
    assert C.classify("https://youtube.com/shorts/dQw4w9WgXcQ") == C.YOUTUBE
    assert C.classify("Circular: https://bvucoep.edu.in/notice.") == C.LINK
    assert C.classify("", "image/jpeg", "IMG-1.jpg") == C.IMAGE
    assert C.classify("", "application/pdf", "x.pdf") == C.PDF
    assert C.classify("", "application/octet-stream", "Notice.PDF") == C.PDF
    assert C.classify("", "audio/ogg", "PTT-1.opus") == C.AUDIO
    assert C.classify("", "video/mp4", "v.mp4") == C.VIDEO
    assert C.classify("", "application/vnd.openxmlformats", "a.docx") == C.DOCUMENT


def test_merge_text_and_urls():
    assert C.merge_text("Check this https://a.com/x", "https://a.com/x") == "Check this https://a.com/x"
    assert C.merge_text("Video title", "https://youtu.be/dQw4w9WgXcQ") == "Video title\nhttps://youtu.be/dQw4w9WgXcQ"
    assert C.find_urls("see (https://example.com/a).") == ["https://example.com/a"]


# ---------------- auth ----------------
def test_password_and_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "SECRET_KEY", "k")
    h = auth.hash_password("pw123456")
    assert auth.check_password("pw123456", h) and not auth.check_password("wrong", h)
    t = auth.make_token("user-1")
    assert auth.read_token(t) == "user-1"
    assert auth.read_token(t[:-1] + ("0" if t[-1] != "0" else "1")) is None   # tampered
    assert auth.read_token("garbage") is None


def test_register_login_rules(env):
    _, client = env
    assert client.get("/api/config").json()["class_code_required"] is True
    bad = client.post("/api/auth/register", json={"name": "X", "email": "x@y.in", "password": "secret1", "class_code": "nope"})
    assert bad.status_code == 403
    signup(client)
    dup = client.post("/api/auth/register", json={"name": "A", "email": "ASHA@bvucoep.edu.in", "password": "secret1", "class_code": "BVDU26"})
    assert dup.status_code == 409
    assert client.post("/api/auth/login", json={"email": "asha@bvucoep.edu.in", "password": "bad"}).status_code == 401
    ok = client.post("/api/auth/login", json={"email": " Asha@bvucoep.edu.in ", "password": "secret123"})
    assert ok.status_code == 200 and ok.json()["name"] == "Asha"
    assert client.get("/api/items").status_code == 401
    assert client.get("/api/items", headers={"Authorization": "Bearer forged.123.abc"}).status_code == 401


def test_change_password(env):
    _, client = env
    h = signup(client)
    assert client.post("/api/me/password", headers=h, json={"old_password": "x", "new_password": "newpass1"}).status_code == 403
    assert client.post("/api/me/password", headers=h, json={"old_password": "secret123", "new_password": "newpass1"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "asha@bvucoep.edu.in", "password": "newpass1"}).status_code == 200


# ---------------- shell ----------------
def test_shell_and_manifest(env):
    _, client = env
    assert client.get("/").status_code == 200
    sw = client.get("/sw.js")
    assert sw.headers["service-worker-allowed"] == "/" and "share-target" in sw.text
    man = client.get("/manifest.webmanifest")
    assert man.json()["share_target"]["action"] == "/share-target"
    assert client.post("/share-target", follow_redirects=False).status_code == 303


# ---------------- ingest -> process ----------------
def test_text_share_uses_users_own_key(env):
    fake, client = env
    h = signup(client)
    r = client.post("/api/ingest", headers=h, data={"client_id": "c1", "text": "HOD: Dept meeting tomorrow 3 pm on NBA"})
    mid = r.json()["id"]
    status = client.get(f"/api/messages/{mid}", headers=h).json()
    assert status["message"]["status"] == "processed" and status["item"]["title"].startswith("Department meeting")
    assert fakes.FAKE_CALLS == ["key-of-Asha"]          # the phone's key reached Gemini
    again = client.post("/api/ingest", headers=h, data={"client_id": "c1", "text": "dup"})
    assert again.json()["id"] == mid and len(fake.messages) == 1


def test_students_cannot_see_each_other(env):
    fake, client = env
    a = signup(client, "a@x.in", "Asha")
    b = signup(client, "b@x.in", "Bala")
    mid = client.post("/api/ingest", headers=a, data={"client_id": "s"},
                      files={"file": ("n.jpg", b"\xff\xd8", "image/jpeg")}).json()["id"]
    # same client_id from another user is a different share
    client.post("/api/ingest", headers=b, data={"client_id": "s", "text": "Bala's note"})
    assert len(client.get("/api/items", headers=a).json()) == 1
    assert client.get("/api/items?q=exam", headers=b).json() == []
    assert client.get(f"/api/messages/{mid}", headers=b).status_code == 404
    assert client.get(f"/api/file/{mid}", headers=b).status_code == 404
    client.delete(f"/api/messages/{mid}", headers=b)                 # cannot delete others' items
    assert mid in fake.messages
    assert fake.messages[mid]["media_path"].startswith(fake.messages[mid]["user_id"] + "/")


def test_image_share(env):
    fake, client = env
    h = signup(client)
    mid = client.post("/api/ingest", headers=h, data={"client_id": "img1"},
                      files={"file": ("IMG-2026.jpg", b"\xff\xd8\xff fake", "image/jpeg")}).json()["id"]
    item = client.get(f"/api/messages/{mid}", headers=h).json()["item"]
    assert item["deadline"] == "2026-10-06" and item["tags"] == ["exam", "form", "deadline"]
    assert client.get(f"/api/file/{mid}", headers=h).json()["url"].startswith("https://")


def test_youtube_share(env, monkeypatch):
    _, client = env
    h = signup(client)
    monkeypatch.setattr(pipeline, "youtube_info", lambda vid, url: {
        "video_id": vid, "url": url, "title": "CNN explained", "channel": "Ch", "transcript": "conv layers"})
    r = client.post("/api/ingest", headers=h, data={"client_id": "yt1", "title": "CNN", "text": "https://youtu.be/dQw4w9WgXcQ"})
    assert r.json()["kind"] == "youtube"
    item = client.get(f"/api/messages/{r.json()['id']}", headers=h).json()["item"]
    assert item["source_meta"]["video_id"] == "dQw4w9WgXcQ" and "transcript" not in item["source_meta"]


def test_audio_stored_not_read(env):
    fake, client = env
    h = signup(client)
    r = client.post("/api/ingest", headers=h, data={"client_id": "a1"}, files={"file": ("PTT.opus", b"OggS", "audio/ogg")})
    assert fake.messages[r.json()["id"]]["status"] == "stored" and not fake.items


def test_failure_then_retry(env):
    fake, client = env
    h = signup(client)
    mid = client.post("/api/ingest", headers=h, data={"client_id": "f1", "text": "FAIL please"}).json()["id"]
    assert fake.messages[mid]["status"] == "failed"
    assert [m["id"] for m in client.get("/api/messages?status=failed", headers=h).json()] == [mid]
    fake.messages[mid]["text_content"] = "fixed now"
    client.post(f"/api/messages/{mid}/retry", headers=h)
    client.post(f"/api/messages/{mid}/retry", headers=h)
    assert fake.messages[mid]["status"] == "processed" and len(fake.items) == 1


def test_validation_and_delete(env):
    fake, client = env
    h = signup(client)
    assert client.post("/api/ingest", headers=h, data={"client_id": "e"}).status_code == 400
    mid = client.post("/api/ingest", headers=h, data={"client_id": "d1", "text": "x"}).json()["id"]
    client.delete(f"/api/messages/{mid}", headers=h)
    assert not fake.messages and not fake.items


# ---------------- Gemini adapter ----------------
def test_friendly_errors():
    assert "limit" in pipeline.friendly_error(Exception("429 RESOURCE_EXHAUSTED quota"))
    assert "rejected" in pipeline.friendly_error(Exception("400 API_KEY_INVALID"))
    assert "Settings" in pipeline.friendly_error(structurer.NoApiKey("No Gemini API key. Add it in Settings"))


def test_structure_requires_key(monkeypatch):
    monkeypatch.setattr(structurer.settings, "ALLOW_SHARED_KEY", False)
    with pytest.raises(structurer.NoApiKey):
        structurer.structure([{"type": "text", "text": "hi"}], None)


def test_structure_calls_gemini_correctly(monkeypatch):
    captured = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            captured.update(model=model, contents=contents, config=config)
            return type("R", (), {"text": json.dumps({
                "category": "Exam", "title": "Form", "summary": "s", "deadline": "", "issue_date": "2026-10-01",
                "key_dates": [{"label": "Last date", "date": "2026-10-06", "time": ""}, {"label": "x", "date": ""}],
                "action_items": [], "tags": [" Exam ", ""]})})()

    class FakeClient:
        def __init__(self, api_key):
            captured["key"] = api_key
            self.models = FakeModels()

    monkeypatch.setattr(structurer.genai, "Client", FakeClient)
    jpeg = base64.b64encode(b"\xff\xd8img").decode()
    out = structurer.structure([
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": jpeg}},
        {"type": "text", "text": "read this"}], "user-key")
    assert captured["key"] == "user-key"
    assert captured["contents"][0].inline_data.data == b"\xff\xd8img"
    assert captured["contents"][1] == "read this"
    assert captured["config"].response_mime_type == "application/json"
    assert out["category"] == "other"                 # not an allowed value -> other
    assert out["deadline"] is None and out["tags"] == ["exam"]
    assert out["key_dates"] == [{"label": "Last date", "date": "2026-10-06", "time": None}]
