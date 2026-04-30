"""Lightweight PII redactor."""

from __future__ import annotations

from agenticos_shared.redaction import redact_messages, redact_text


def test_email_phone_ssn_ipv4_redacted():
    text = (
        "Hi alice@example.com, call me at +1 415-555-1234. "
        "My SSN is 123-45-6789 and my IP was 192.168.1.42."
    )
    out, stats = redact_text(text)
    assert "[REDACTED:email]" in out
    assert "alice@example.com" not in out
    assert "[REDACTED:ssn]" in out
    assert "[REDACTED:ipv4]" in out
    assert "[REDACTED:phone]" in out
    assert stats.total >= 4


def test_credit_card_only_when_luhn_passes():
    valid_cc = "4111 1111 1111 1111"  # canonical Visa test number
    text = f"My card is {valid_cc} please."
    out, stats = redact_text(text)
    assert "[REDACTED:cc]" in out
    assert valid_cc not in out
    assert stats.counts.get("cc", 0) >= 1


def test_credit_card_invalid_luhn_left_alone():
    bad = "1234 5678 9012 3456"
    out, _ = redact_text(f"random {bad}")
    # Either left alone or scrubbed as a secret/phone — what matters is
    # that the cc rule rejected it.
    assert "[REDACTED:cc]" not in out


def test_obvious_secret_token_redacted():
    text = (
        "Use API key sk-thisIsAFakeApiKey1234567890ABCDEF, "
        "also try aos_abcdefghijklmnopqrstuvwxyzABCDEFGH."
    )
    out, stats = redact_text(text)
    assert "sk-thisIsAFakeApiKey1234567890ABCDEF" not in out
    assert "aos_abcdefghijklmnopqrstuvwxyzABCDEFGH" not in out
    # Either both matched the secret rule, or one fell through to a more
    # generic redaction tag — either way, neither plaintext survives.
    assert stats.total >= 2


def test_messages_walked_recursively():
    msgs = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "I'm alice@example.com"},
        {"role": "tool", "content": "Token: aos_abcdefghijklmnopqrstuvwxyz12"},
    ]
    out, stats = redact_messages(msgs)
    assert "[REDACTED:email]" in out[1]["content"]
    assert "[REDACTED:secret]" in out[2]["content"]
    assert stats.total >= 2
