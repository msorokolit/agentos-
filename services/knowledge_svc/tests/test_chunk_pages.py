"""chunk_pages stamps each chunk's meta.page so PDF citations can
surface page numbers (PLAN §13 P3)."""

from __future__ import annotations

from knowledge_svc.chunker import chunk_pages


def test_pages_get_consecutive_meta():
    pages = [
        "Intro paragraph for page one. " * 5,
        "",  # empty page should be skipped without bumping the counter
        "Methodology page contents. " * 5,
        "Conclusions and references on the last page. " * 5,
    ]
    chunks = chunk_pages(pages, chunk_size=120, overlap=20)
    assert chunks
    seen_pages = sorted({c.meta["page"] for c in chunks})
    # Pages 1, 3, 4 produced chunks; page 2 was empty and skipped.
    assert seen_pages == [1, 3, 4]
    # Ord stays globally increasing.
    ords = [c.ord for c in chunks]
    assert ords == sorted(ords)
    assert ords[0] == 0


def test_meta_carries_base_metadata_alongside_page():
    chunks = chunk_pages(
        ["hello world"],
        chunk_size=100,
        overlap=10,
        base_meta={"source": "doc-42"},
    )
    assert chunks
    assert chunks[0].meta == {"source": "doc-42", "page": 1}
