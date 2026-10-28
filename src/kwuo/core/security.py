"""Security utilities: Argon2 password hashing and JWT session tokens."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from kwuo.core.config import settings

# Argon2 password hasher
ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

ALGORITHM = "HS256"
SESSION_COOKIE_NAME = "kwuo_session"
DEFAULT_SESSION_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """Hash plaintext password with Argon2."""
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify plaintext password against an Argon2 hash."""
    try:
        return ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_session_token(user_id: str, expires_delta: Optional[timedelta] = None) -> str:
    """Generate a signed JWT session token."""
    expire = datetime.now(timezone.utc) + (
        expires_delta if expires_delta else timedelta(days=DEFAULT_SESSION_EXPIRE_DAYS)
    )
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_session_token(token: str) -> Optional[Dict[str, Any]]:
    """Decode and validate a JWT session token."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except (jwt.PyJWTError, Exception):
        return None
