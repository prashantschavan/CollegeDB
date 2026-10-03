"""Central configuration, loaded from environment variables / .env file."""
import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes")


class Settings:
    # Signs login tokens. Long random string; changing it logs everyone out.
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    # Students need this code to create an account (stops strangers signing up). Blank = open sign-up.
    CLASS_CODE = os.getenv("CLASS_CODE", "")

    # --- Google Gemini (free tier: aistudio.google.com/apikey) ---
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    # Optional shared key used when a user hasn't added their own (only if ALLOW_SHARED_KEY=true).
    # Free-tier limits are per Google project, so a shared key is split across everyone using it.
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    ALLOW_SHARED_KEY = _bool("ALLOW_SHARED_KEY", "false")

    # --- Supabase ---
    SUPABASE_URL = os.getenv("SUPABASE_URL", "")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service_role key (server-side only!)
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "wa-media")

    # --- Optional ---
    YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "")
    FETCH_TRANSCRIPTS = _bool("FETCH_TRANSCRIPTS", "true")
    TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
    TOKEN_DAYS = int(os.getenv("TOKEN_DAYS", "180"))


settings = Settings()
