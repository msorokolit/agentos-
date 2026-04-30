"""Lightweight regex-based PII redactor.

Used by the llm-gateway to scrub outbound LLM payloads when a workspace
opts in (``settings.redact_outbound_payloads``). The goal is "good
hygiene" — block obvious PII from leaving the cluster — not formal
classification. For real DLP, swap in Presidio at the same call site.

Matched categories (with their replacement tag):

* ``[REDACTED:email]``  — email addresses
* ``[REDACTED:phone]``  — international phone numbers
* ``[REDACTED:ssn]``    — US SSN
* ``[REDACTED:cc]``     — 13-19 digit credit-card numbers passing Luhn
* ``[REDACTED:ipv4]``   — IPv4 addresses
* ``[REDACTED:secret]`` — anything looking like an API key / bearer
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Heuristic but conservative regexes. Order matters: token-y patterns
# come before phones (so ``api_key=... 19374759262`` doesn't get tagged
# as a phone number).
_RX = [
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("ipv4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    (
        "secret",
        re.compile(
            r"\b(?:sk|aos|ghp|gho|ghu|ghs|xox[bpoa])_[A-Za-z0-9_\-]{16,}|"
            r"\bAKIA[0-9A-Z]{16}\b|"
            r"\b[A-Za-z0-9_\-]{40,}\b",
        ),
    ),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # ``cc`` runs before ``phone`` so a 16-digit card number doesn't get
    # mis-tagged as a phone number.
    ("cc", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    (
        "phone",
        re.compile(
            r"(?<!\d)\+?\d[\d\s().-]{8,18}\d(?!\d)",
        ),
    ),
]


def _luhn_ok(digits: str) -> bool:
    s = 0
    rev = digits[::-1]
    for i, ch in enumerate(rev):
        if not ch.isdigit():
            return False
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        s += n
    return s % 10 == 0


@dataclass
class RedactionStats:
    counts: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact_text(text: str) -> tuple[str, RedactionStats]:
    """Apply every matcher to ``text``; return ``(scrubbed, stats)``."""

    counts: dict[str, int] = {}

    def _make_sub(tag: str):
        def _sub(m: re.Match[str]) -> str:
            counts[tag] = counts.get(tag, 0) + 1
            return f"[REDACTED:{tag}]"

        return _sub

    def _make_cc(tag: str):
        def _cc(m: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and _luhn_ok(digits):
                counts[tag] = counts.get(tag, 0) + 1
                return f"[REDACTED:{tag}]"
            return m.group(0)

        return _cc

    for tag, rx in _RX:
        replacer = _make_cc(tag) if tag == "cc" else _make_sub(tag)
        text = rx.sub(replacer, text)
    return text, RedactionStats(counts=counts)


def redact_messages(
    messages: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], RedactionStats]:
    """Walk a list of OpenAI chat messages and redact ``content`` strings."""

    out: list[dict[str, Any]] = []
    total: dict[str, int] = {}
    for m in messages:
        msg = dict(m)
        if isinstance(msg.get("content"), str):
            scrubbed, stats = redact_text(msg["content"])
            msg["content"] = scrubbed
            for k, v in stats.counts.items():
                total[k] = total.get(k, 0) + v
        out.append(msg)
    return out, RedactionStats(counts=total)
