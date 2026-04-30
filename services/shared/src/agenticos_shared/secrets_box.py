"""Encryption helpers for secrets at rest.

We use libsodium's SecretBox (XSalsa20-Poly1305) via PyNaCl. A per-process
key is derived from ``AGENTICOS_SECRET_KEY`` (any length \u2265 32 bytes
recommended) using BLAKE2b-256 so the same secret material rotates
cleanly when ops change ``AGENTICOS_SECRET_KEY`` and run a re-encryption
job. Per-tenant KEKs / KMS adapters are out of scope here \u2014 this is
the in-process baseline.

Stored payload format: ``"v1:" + base64url(nonce(24) || ciphertext)``.
That single string is what callers persist in JSON columns; ``decrypt``
inspects the version prefix so we can bump the algorithm later.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from nacl import secret, utils

_VERSION = "v1"
_KEY_BYTES = 32


def _derive_key(material: str) -> bytes:
    if not material:
        raise ValueError("AGENTICOS_SECRET_KEY is empty; cannot derive box key")
    return hashlib.blake2b(material.encode("utf-8"), digest_size=_KEY_BYTES).digest()


def encrypt(plaintext: str, *, key_material: str) -> str:
    box = secret.SecretBox(_derive_key(key_material))
    nonce = utils.random(secret.SecretBox.NONCE_SIZE)
    ct = box.encrypt(plaintext.encode("utf-8"), nonce).ciphertext
    blob = nonce + ct
    return f"{_VERSION}:{base64.urlsafe_b64encode(blob).decode().rstrip('=')}"


def decrypt(envelope: str, *, key_material: str) -> str:
    version, _, payload = envelope.partition(":")
    if version != _VERSION:
        raise ValueError(f"unsupported secret envelope version: {version!r}")
    pad = "=" * (-len(payload) % 4)
    blob = base64.urlsafe_b64decode((payload + pad).encode())
    nonce, ct = blob[: secret.SecretBox.NONCE_SIZE], blob[secret.SecretBox.NONCE_SIZE :]
    box = secret.SecretBox(_derive_key(key_material))
    return box.decrypt(ct, nonce).decode("utf-8")


def looks_encrypted(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(f"{_VERSION}:")


# ---------------------------------------------------------------------------
# Field-level helpers for descriptors
# ---------------------------------------------------------------------------
SENSITIVE_KEY_TOKENS = (
    "secret",
    "password",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "bearer",
    "authorization",
    "client_secret",
)


def _is_sensitive(key: str) -> bool:
    # Normalise dashes/spaces to underscores so e.g. ``X-Api-Key`` matches
    # the ``api_key`` token.
    k = key.lower().replace("-", "_").replace(" ", "_")
    return any(t in k for t in SENSITIVE_KEY_TOKENS)


def encrypt_sensitive_fields(
    payload: Any,
    *,
    key_material: str,
) -> Any:
    """Walk a JSON-shaped value and encrypt every string field whose key
    name looks sensitive. Already-encrypted values are left alone."""

    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for k, v in payload.items():
            if _is_sensitive(k) and isinstance(v, str) and v and not looks_encrypted(v):
                out[k] = encrypt(v, key_material=key_material)
            else:
                out[k] = encrypt_sensitive_fields(v, key_material=key_material)
        return out
    if isinstance(payload, list):
        return [encrypt_sensitive_fields(v, key_material=key_material) for v in payload]
    return payload


def decrypt_sensitive_fields(
    payload: Any,
    *,
    key_material: str,
) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for k, v in payload.items():
            if isinstance(v, str) and looks_encrypted(v):
                try:
                    out[k] = decrypt(v, key_material=key_material)
                except Exception:
                    out[k] = v
            else:
                out[k] = decrypt_sensitive_fields(v, key_material=key_material)
        return out
    if isinstance(payload, list):
        return [decrypt_sensitive_fields(v, key_material=key_material) for v in payload]
    return payload
