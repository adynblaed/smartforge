"""At-rest encryption for sensitive stored content (AI chats / interactions).

App-level symmetric encryption (Fernet = AES-128-CBC + HMAC-SHA256). The key is
derived from ``SECRET_KEY``, so the ciphertext persisted in Postgres is unreadable
without the application secret — a DB dump or breach does not expose chat content.

Reads degrade gracefully: values without the ``enc::`` marker (legacy plaintext)
are returned as-is, and any decryption failure falls back to the raw value so the
app never hard-fails on a key rotation.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

if TYPE_CHECKING:
    from cryptography.fernet import Fernet
    from sqlalchemy.engine import Dialect

_PREFIX = "enc::"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    from cryptography.fernet import Fernet

    key = base64.urlsafe_b64encode(
        hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    )
    return Fernet(key)


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    return _PREFIX + _fernet().encrypt(plaintext.encode()).decode()


def decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.startswith(_PREFIX):
        return value  # legacy plaintext written before encryption was enabled
    try:
        return _fernet().decrypt(value[len(_PREFIX) :].encode()).decode()
    except Exception:
        # Return the stored value rather than break reads, but never
        # silently: a decrypt failure means SECRET_KEY rotated without
        # re-encryption — that's an operator problem, not a data problem.
        logging.getLogger(__name__).warning(
            "decrypt failed for an encrypted column value; returning stored "
            "form (was SECRET_KEY rotated without re-encrypting?)"
        )
        return value


class EncryptedString(TypeDecorator[str]):
    """A text column whose value is transparently encrypted at rest.

    Stored as unbounded TEXT because ciphertext is longer than the plaintext.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return encrypt(value) if value is not None else None

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return decrypt(value) if value is not None else None
