"""Accounts: password hashing and signed login tokens (no extra services needed)."""
import base64
import hashlib
import hmac
import os
import time

from .config import settings


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def check_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, hash_b64 = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except Exception:
        return False


def _sign(payload: str) -> str:
    if not settings.SECRET_KEY:
        raise RuntimeError("SECRET_KEY is not configured on the server")
    return hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: str) -> str:
    payload = f"{user_id}.{int(time.time()) + settings.TOKEN_DAYS * 86400}"
    return f"{payload}.{_sign(payload)}"


def read_token(token: str) -> str | None:
    """Returns the user id if the token is genuine and not expired."""
    try:
        user_id, exp, sig = token.rsplit(".", 2)
        if not hmac.compare_digest(sig, _sign(f"{user_id}.{exp}")):
            return None
        if int(exp) < time.time():
            return None
        return user_id
    except (ValueError, AttributeError):
        return None
