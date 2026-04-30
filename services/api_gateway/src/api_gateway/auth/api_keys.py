"""API-key minting + verification.

Format: ``aos_<32 url-safe base64 chars>`` (37 chars total).
We store only ``sha256(token)`` plus the first 8 chars (``prefix``) so the
plaintext token is never recoverable.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

KEY_PREFIX = "aos_"
PREFIX_LEN = 8


def mint_token() -> tuple[str, str, str]:
    """Return (plaintext, prefix, sha256-hex)."""

    raw = secrets.token_urlsafe(24)
    plaintext = f"{KEY_PREFIX}{raw}"
    prefix = plaintext[:PREFIX_LEN]
    digest = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    return plaintext, prefix, digest


def hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


@dataclass
class TokenInfo:
    prefix: str
    hashed: str

    @classmethod
    def from_plaintext(cls, plaintext: str) -> TokenInfo:
        return cls(prefix=plaintext[:PREFIX_LEN], hashed=hash_token(plaintext))
