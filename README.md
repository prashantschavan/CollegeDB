# My Saver: share from WhatsApp, saved and searchable (free, multi-user)

Students and staff install Saver on their Android phones. In WhatsApp they long-press a notice photo, PDF, link, or
message, tap **Share**, and pick **Saver**. Google Gemini reads it and saves a structured record: category, title, summary,
issuing authority, reference number, deadline, key dates, action items, and tags. Each person sees only their own items.

**It's free for everyone.** Each student uses their own free Gemini key, which takes 2 minutes to get and needs no card. Supabase and Render are free at class scale.
There's no APK, no bot number, and no WhatsApp Business setup. The app is a PWA that installs from Chrome.

```
 WhatsApp ──Share──► Saver app (phone)  ── key stays on phone, sent per request ──┐
                       │ share parked on phone first (nothing lost if offline)       │
                       ▼                                                             ▼
                 POST /api/ingest ──► FastAPI (Render) ──► Gemini (student's own free key)
                                         │
                                         ▼
                 Supabase: users · messages (raw) · items (structured) · files — all per user
```

## Features
- **Accounts**: email + password + class code (the code stops strangers from signing up). Students can change their own password.
- **Share target**: Saver appears in Android's Share menu for images, PDFs, links, text, audio, and video.
- **All / Upcoming / Needs review** tabs, with search (partial words and tags work) and a category filter.
- **Original**: opens your original image or PDF through a private, expiring link.
- **Add manually**: paste text or pick files. This also works on iPhone and desktop.
- **Clear error messages**: for example, "Free Gemini limit reached, tap Retry later" or "Your key was rejected, check Settings".

## Layout
| Path | Purpose |
|---|---|
| `app/main.py` | API, accounts, serves the app |
| `app/auth.py` | Password hashing (scrypt) and signed login tokens |
| `app/structurer.py` | Gemini prompt + output fields (edit categories here) |
| `app/pipeline.py` | Reads one share and saves the item (also used by Retry) |
| `app/classifier.py`, `app/extractors/` | Content type detection; image/PDF/YouTube/web extraction |
| `app/db.py`, `schema.sql` | Supabase tables, per-user search, file storage |
| `app/static/` | The phone app (HTML/JS/CSS, service worker, manifest, icons) |
| `render.yaml` | One-click deployment on Render |
| `reset_password.py` | Teacher tool: reset a student's password |
| `try_local.py` | Test extraction on your own files with your Gemini key |
| `tests/` | Offline tests (`pytest`) |

## Deploy (teacher, one time)
1. **Supabase**: create a project (Mumbai region). In SQL Editor, paste all of `schema.sql` and click Run. Then copy the Project URL and the service_role key.
2. **GitHub**: create a private repo and upload the contents of the `my-saver` folder. Do not upload `.env`.
3. **Render**: choose New → Blueprint and pick the repo. Fill in `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, and `CLASS_CODE`. You get `https://my-saver-xxxx.onrender.com`.
4. Share that link and the class code with students.

> The free Render plan sleeps after 15 minutes idle, so the first share after a break takes about 50 seconds to wake it.
> The app retries automatically. Free limits are 512 MB RAM on Render, and a 500 MB database plus 1 GB file storage on Supabase.
> That's roughly 5,000 notice photos across the class.

## Install (each student)
1. Open the link in **Chrome** on Android. Tap **Create account** and enter your name, email, a password, and the class code.
2. Tap **Add key**, open aistudio.google.com/apikey, choose **Create API key**, copy it, paste it, and tap **Save**.
3. Use Chrome menu ⋮ → **Add to Home screen / Install app**. Open Saver once from the home screen.
4. In WhatsApp, long-press a message → Share → **Saver**. You may need to tap "More" the first time.

## Good to know
- **Gemini free tier**: limits are per Google project, so each student has their own quota. Google may use free-tier content to improve its products,
  so students shouldn't share confidential documents.
- **Text messages**: some WhatsApp versions have no Share option for plain text. Copy the text and use **Add manually**.
- **iPhone**: iOS can't add web apps to the Share menu. Use **Add manually**.
- **Forgotten password**: run `python reset_password.py student@email NewPass123` on your PC with `.env` filled in.
- **Changing the model**: set `GEMINI_MODEL` on Render, for example to a newer Flash model listed in AI Studio.

## Test locally (optional)
```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                   # 16 passed
copy .env.example .env                      # add GEMINI_API_KEY
python try_local.py "C:\path\notice.jpg"
```
