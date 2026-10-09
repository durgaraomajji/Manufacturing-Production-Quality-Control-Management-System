"""Password hashing and JWT helpers."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import AuthenticationError

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    # bcrypt only considers the first 72 bytes
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def _create_token(subject: int, token_type: str, expires: timedelta, extra: dict | None = None) -> tuple[str, str, datetime]:
    now = datetime.now(timezone.utc)
    jti = uuid.uuid4().hex
    exp = now + expires
    payload = {"sub": str(subject), "type": token_type, "jti": jti, "iat": now, "exp": exp, **(extra or {})}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, jti, exp.replace(tzinfo=None)


def create_access_token(user_id: int, role: str) -> tuple[str, str, datetime]:
    return _create_token(user_id, ACCESS, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), {"role": role})


def create_refresh_token(user_id: int) -> tuple[str, str, datetime]:
    return _create_token(user_id, REFRESH, timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except jwt.PyJWTError:
        raise AuthenticationError("Invalid token")
    if payload.get("type") != expected_type:
        raise AuthenticationError(f"Invalid token type (expected {expected_type})")
    return payload


def generate_reset_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash). Only the hash is stored."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
