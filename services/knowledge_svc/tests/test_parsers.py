"""Parsers (markdown / html / plain). PDF parsing requires a real PDF
document, so we generate one with pypdf in the test."""

from __future__ import annotations

import io

from knowledge_svc.ingest.parsers import extract_text


def test_markdown_strips_frontmatter() -> None:
    md = b"""---
title: Hello
---

# Heading

Body paragraph.
"""
    out = extract_text(blob=md, mime="text/markdown", filename="x.md")
    assert "title: Hello" not in out.text
    assert "Heading" in out.text


def test_html_strips_scripts_and_extracts_title() -> None:
    html = b"""<html><head><title>My Page</title></head>
    <body><script>alert(1)</script><p>Hello <b>World</b></p></body></html>"""
    out = extract_text(blob=html, mime="text/html")
    assert "alert(1)" not in out.text
    assert "Hello" in out.text and "World" in out.text
    assert out.meta.get("title") == "My Page"


def test_plain_fallback_for_unknown_mime() -> None:
    out = extract_text(blob=b"raw text", mime="application/octet-stream", filename="x.bin")
    assert out.text == "raw text"


def test_pdf_roundtrip() -> None:
    # Build a minimal PDF in memory using pypdf.
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    blob = buf.getvalue()
    out = extract_text(blob=blob, mime="application/pdf", filename="x.pdf")
    # The PDF has no text, so .text is empty, but pages list is populated.
    assert out.meta.get("page_count") == "1"
