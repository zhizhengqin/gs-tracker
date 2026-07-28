"""Authentication and authorization: password hashing, sessions, guards."""
import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.storage import (
    count_users,
    create_user,
    delete_session,
    get_session,
    get_user,
    save_session,
)

logger = logging.getLogger(__name__)

SESSION_COOKIE = "gs_session"
SESSION_TTL_DAYS = 7

DEFAULT_ADMIN_USERNAME = "gsadmin"
DEFAULT_ADMIN_PASSWORD = "admin123"

_PBKDF2_ITERATIONS = 100_000


def hash_password(password: str) -> str:
    """Hash a password as 'pbkdf2$iterations$salt_hex$hash_hex'."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return f"pbkdf2${_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Check a password against a stored pbkdf2 hash (constant-time)."""
    try:
        scheme, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return secrets.compare_digest(digest.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def ensure_default_admin() -> None:
    """Create the built-in admin account on first run (no users at all)."""
    try:
        if count_users() > 0:
            return
        create_user(
            DEFAULT_ADMIN_USERNAME,
            hash_password(DEFAULT_ADMIN_PASSWORD),
            role="admin",
        )
        logger.info("Created built-in admin account '%s'", DEFAULT_ADMIN_USERNAME)
    except Exception:
        logger.exception("Failed to seed default admin account")


def authenticate(username: str, password: str) -> Optional[dict]:
    """Return the user dict if credentials are valid, else None."""
    user = get_user(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {"username": user["username"], "role": user["role"]}


def create_session(username: str) -> str:
    """Issue a new session token for a user."""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)
    save_session(token, username, expires_at)
    return token


def destroy_session(token: str) -> None:
    """Invalidate a session token (logout)."""
    delete_session(token)


def current_user_from_token(token: Optional[str]) -> Optional[dict]:
    """Resolve a session token to {'username', 'role'} or None."""
    if not token:
        return None
    session = get_session(token)
    if not session:
        return None
    return {"username": session["username"], "role": session["role"]}
