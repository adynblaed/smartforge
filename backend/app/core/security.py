from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta,
    *,
    role: str | None = None,
    is_superuser: bool | None = None,
) -> str:
    """Mint a signed access token for ``subject``.

    ``role`` / ``is_superuser`` are embedded as claims so the rate-limit
    middleware can resolve a caller's tier without a DB hit (API-017/SEC-012).
    Both are optional for backward compatibility; tokens without the claims
    stay valid and are treated as the lowest authenticated tier (customer)
    by app/core/ratelimit.py.
    """
    expire = datetime.now(timezone.utc) + expires_delta
    to_encode: dict[str, Any] = {"exp": expire, "sub": str(subject)}
    if role is not None:
        to_encode["role"] = role
    if is_superuser is not None:
        to_encode["is_superuser"] = is_superuser
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)
