"""Tiny eval runner for the YAML eval format documented in README.md.

* Heuristic scorers only (substring inclusion / exclusion / length).
* Talks to the api-gateway via Bearer-token API key.
* Exits with code 1 if any case fails (CI gate-friendly).

LLM-as-judge scoring lives in v1.5.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass
class CaseResult:
    name: str
    ok: bool
    answer: str
    reasons: list[str]


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml  # lazy import — keeps the module importable for `--help`

    return yaml.safe_load(path.read_text())


def _expand_id(raw: str, env_key: str) -> str:
    if raw == "00000000-0000-0000-0000-000000000000":
        v = os.environ.get(env_key)
        if not v:
            raise SystemExit(f"set {env_key} or replace the placeholder in the YAML")
        return v
    return raw


def _score(case: dict[str, Any], answer: str) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    lo = answer.lower()
    for needle in case.get("expect_contains", []) or []:
        if needle.lower() not in lo:
            reasons.append(f"missing expected substring: {needle!r}")
    for needle in case.get("forbid_contains", []) or []:
        if needle.lower() in lo:
            reasons.append(f"forbidden substring present: {needle!r}")
    min_length = case.get("min_length")
    if isinstance(min_length, int) and len(answer) < min_length:
        reasons.append(f"answer too short ({len(answer)} < {min_length})")
    return (not reasons), reasons


def run_set(*, base_url: str, token: str, yaml_path: Path) -> int:
    spec = _load_yaml(yaml_path)
    workspace_id = _expand_id(spec["workspace_id"], "AGENTICOS_WORKSPACE_ID")
    agent_id = _expand_id(spec["agent_id"], "AGENTICOS_AGENT_ID")

    print(f"== eval set: {spec.get('name')} ({len(spec.get('cases') or [])} cases)")
    headers = {"Authorization": f"Bearer {token}"}
    fails: list[CaseResult] = []
    with httpx.Client(timeout=300.0, headers=headers) as c:
        for i, case in enumerate(spec.get("cases") or [], start=1):
            r = c.post(
                f"{base_url}/api/v1/workspaces/{workspace_id}/agents/{agent_id}/run",
                json={"user_message": case["input"]},
            )
            r.raise_for_status()
            ans = r.json().get("final_message") or ""
            ok, reasons = _score(case, ans)
            line = f"  {'PASS' if ok else 'FAIL':<5} [{i}] {case['input'][:60]}"
            print(line)
            if not ok:
                for reason in reasons:
                    print(f"          ! {reason}")
                print(f"          → {ans[:120]}")
                fails.append(CaseResult(name=case["input"], ok=False, answer=ans, reasons=reasons))

    if fails:
        print(f"\n{len(fails)} case(s) failed.")
        return 1
    print("\nAll cases passed.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default=os.environ.get("AGENTICOS_API", "http://localhost:8080"))
    p.add_argument("--token", default=os.environ.get("AGENTICOS_TOKEN"))
    p.add_argument("--set", required=True, type=Path)
    args = p.parse_args()
    if not args.token:
        print("ERROR: --token or AGENTICOS_TOKEN required", file=sys.stderr)
        return 2
    return run_set(base_url=args.base_url, token=args.token, yaml_path=args.set)


if __name__ == "__main__":
    sys.exit(main())
