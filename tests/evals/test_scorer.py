"""Unit-test the eval scorer (heuristic substring/length checks)."""

from __future__ import annotations

import sys
from pathlib import Path

# Add the evals dir to sys.path so we can import runner directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from runner import _score


def test_expect_contains_passes():
    ok, reasons = _score({"expect_contains": ["paris"]}, "The capital is Paris.")
    assert ok and reasons == []


def test_forbid_contains_fails():
    ok, reasons = _score(
        {"expect_contains": ["paris"], "forbid_contains": ["London"]},
        "Paris and London",
    )
    assert not ok
    assert any("London" in r for r in reasons)


def test_min_length():
    ok, reasons = _score({"min_length": 5}, "hi")
    assert not ok
    assert "too short" in reasons[0]


def test_passes_with_no_constraints():
    ok, reasons = _score({}, "")
    assert ok and reasons == []
