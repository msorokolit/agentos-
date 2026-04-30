"""Chunker behaviour."""

from __future__ import annotations

import pytest
from knowledge_svc.chunker import chunk_text, count_tokens


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n   \n") == []


def test_short_text_one_chunk() -> None:
    chunks = chunk_text("hello world", chunk_size=100, overlap=10)
    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].token_count > 0


def test_paragraph_packing_and_overlap() -> None:
    paragraphs = ["A " * 100, "B " * 100, "C " * 100]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, chunk_size=120, overlap=20)
    assert len(chunks) >= 2
    # Each chunk respects size budget (with some slack for paragraph boundaries)
    for c in chunks:
        assert c.token_count <= 120 + 20  # overlap window
    # Ord increments
    for i, c in enumerate(chunks):
        assert c.ord == i


def test_huge_paragraph_is_hard_split() -> None:
    text = "x " * 1000
    chunks = chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) >= 5  # many chunks
    for c in chunks:
        assert c.token_count <= 100


def test_overlap_must_be_smaller_than_chunk_size() -> None:
    with pytest.raises(ValueError):
        chunk_text("abc", chunk_size=10, overlap=10)


def test_count_tokens_monotonic() -> None:
    assert count_tokens("hi") < count_tokens("hi there world")
