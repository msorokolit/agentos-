"""Dump OpenAPI schema for every service into ``out_dir``.

Usage:
    python -m scripts.openapi_snapshot /tmp/openapi
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SERVICES = (
    "api_gateway",
    "agent_runtime",
    "llm_gateway",
    "tool_registry",
    "knowledge_svc",
    "memory_svc",
)


def main() -> int:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} OUT_DIR", file=sys.stderr)
        return 2
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    for svc in SERVICES:
        try:
            m = importlib.import_module(f"{svc}.main")
            schema = m.app.openapi()
        except Exception as exc:
            print(f"skip {svc}: {exc}", file=sys.stderr)
            continue
        target = out / f"{svc}.json"
        target.write_text(json.dumps(schema, indent=2, sort_keys=True))
        print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
