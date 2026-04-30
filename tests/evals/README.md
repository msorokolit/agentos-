# Evaluation harness

Lightweight YAML-driven eval suite that runs an agent against a small set
of canned prompts, scores the answers heuristically, and prints a summary.

This is the v1 scaffold from PLAN §10 — not yet wired into CI.
v1.5 will add an LLM-as-judge scorer + a regression gate.

## Layout

```
tests/evals/
├── README.md              this file
├── runner.py              loads sets, calls agent, scores, prints
└── sets/
    └── smoke.yaml         tiny example set (3 cases)
```

## Format

```yaml
name: smoke
description: A few obvious questions to keep the lights on.
agent_id: 00000000-...     # uuid in the workspace under test
workspace_id: 00000000-... # uuid

cases:
  - input: "What is 2 + 2?"
    expect_contains: ["4"]
  - input: "Capital of France?"
    expect_contains: ["Paris"]
    forbid_contains: ["London"]
  - input: "Say hello."
    min_length: 1
```

Run:

```bash
python -m tests.evals.runner --base-url http://localhost:8080 \
    --token $AGENTICOS_TOKEN --set tests/evals/sets/smoke.yaml
```
