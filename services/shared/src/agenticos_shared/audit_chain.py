"""Audit-log hash chain.

Each row in ``audit_event`` carries a SHA-256 ``event_hash`` over the
canonical JSON of the row plus the ``event_hash`` of the previous row.
Tampering with any earlier row breaks every subsequent hash, so the
chain can be replayed offline (see ``verify_chain``) to detect it.

Canonical form is a sorted-key JSON of a stable subset of fields so that
adding new optional columns later does not invalidate older hashes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

# Genesis hash: 64 zeroes. The first ever row links back to this so the
# verifier doesn't need a separate special case.
GENESIS_HASH: str = "0" * 64

# Fields that participate in the canonical hash. Order is stable; any
# change here is a hard chain reset (require a fresh GENESIS commit).
_HASHED_FIELDS: tuple[str, ...] = (
    "id",
    "tenant_id",
    "workspace_id",
    "actor_id",
    "actor_email",
    "action",
    "resource_type",
    "resource_id",
    "request_id",
    "ip",
    "user_agent",
    "decision",
    "reason",
    "payload",
    "created_at",
)


def _coerce(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        # Force UTC-tagged ISO-8601 so naive datetimes (e.g. from SQLite) and
        # tz-aware ones (Postgres) hash identically.
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _coerce(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_coerce(v) for v in value]
    return value


def canonical_payload(row: Any) -> dict[str, Any]:
    """Project a row (ORM or dict-ish) into the hash-input dict."""

    if isinstance(row, dict):
        getter = row.get
    else:

        def getter(name: str, default: Any = None) -> Any:
            return getattr(row, name, default)

    out: dict[str, Any] = {}
    for f in _HASHED_FIELDS:
        out[f] = _coerce(getter(f))
    return out


def compute_event_hash(row: Any, *, prev_hash: str) -> str:
    """``sha256(prev_hash || canonical_event_json)`` as hex."""

    canon = canonical_payload(row)
    blob = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(blob.encode("utf-8"))
    return h.hexdigest()


def verify_chain(rows: list[Any]) -> dict[str, Any]:
    """Walk a list of audit rows in chronological order and return a
    structured verification report.

    Rows must already be sorted by ``created_at, id``. Returns::

        {
          "ok": bool,
          "checked": int,
          "ok_count": int,
          "broken_count": int,
          "broken": [{"id": str, "reason": str, "expected": str, "got": str}, ...],
        }
    """

    prev = GENESIS_HASH
    broken: list[dict[str, Any]] = []
    ok_count = 0

    for row in rows:
        rid = str(getattr(row, "id", "?"))
        stored_prev = getattr(row, "prev_hash", None)
        stored_hash = getattr(row, "event_hash", None)
        if stored_hash is None:
            # Pre-chain row: skip but keep our running prev so subsequent
            # chained rows still match.
            continue
        expected = compute_event_hash(row, prev_hash=prev)
        if stored_prev not in (prev, None):
            broken.append(
                {
                    "id": rid,
                    "reason": "prev_hash mismatch",
                    "expected": prev,
                    "got": stored_prev,
                }
            )
        elif stored_hash != expected:
            broken.append(
                {
                    "id": rid,
                    "reason": "event_hash mismatch",
                    "expected": expected,
                    "got": stored_hash,
                }
            )
        else:
            ok_count += 1
        prev = stored_hash

    return {
        "ok": not broken,
        "checked": ok_count + len(broken),
        "ok_count": ok_count,
        "broken_count": len(broken),
        "broken": broken,
    }
