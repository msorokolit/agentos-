"""SecretBox-based at-rest encryption helpers."""

from __future__ import annotations

import pytest
from agenticos_shared.secrets_box import (
    decrypt,
    decrypt_sensitive_fields,
    encrypt,
    encrypt_sensitive_fields,
    looks_encrypted,
)

KEY = "test-key-material-must-be-at-least-32-bytes!!"


def test_roundtrip():
    ct = encrypt("hunter2", key_material=KEY)
    assert looks_encrypted(ct)
    assert decrypt(ct, key_material=KEY) == "hunter2"


def test_two_encryptions_differ_random_nonce():
    a = encrypt("same", key_material=KEY)
    b = encrypt("same", key_material=KEY)
    assert a != b
    assert decrypt(a, key_material=KEY) == "same"
    assert decrypt(b, key_material=KEY) == "same"


def test_wrong_key_fails_to_decrypt():
    from nacl.exceptions import CryptoError

    ct = encrypt("hunter2", key_material=KEY)
    with pytest.raises(CryptoError):
        decrypt(ct, key_material="another-completely-different-key-material!")


def test_walks_dict_and_encrypts_only_sensitive_keys():
    payload = {
        "endpoint": "https://api.example.com",
        "headers": {
            "Content-Type": "application/json",
            "X-Api-Key": "sk-secret",
            "Authorization": "Bearer abc",
        },
        "json_body_template": {"hello": "{{args.q}}"},
    }
    enc = encrypt_sensitive_fields(payload, key_material=KEY)
    assert enc["endpoint"] == "https://api.example.com"
    assert enc["headers"]["Content-Type"] == "application/json"
    assert enc["headers"]["X-Api-Key"].startswith("v1:")
    assert enc["headers"]["Authorization"].startswith("v1:")
    # Roundtrip everything back.
    dec = decrypt_sensitive_fields(enc, key_material=KEY)
    assert dec["headers"]["X-Api-Key"] == "sk-secret"
    assert dec["headers"]["Authorization"] == "Bearer abc"


def test_already_encrypted_values_left_alone():
    once = encrypt_sensitive_fields({"api_key": "raw"}, key_material=KEY)
    twice = encrypt_sensitive_fields(once, key_material=KEY)
    assert once == twice
