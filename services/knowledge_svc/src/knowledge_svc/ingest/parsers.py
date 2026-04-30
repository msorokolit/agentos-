"""File parsers — PDF, HTML, Markdown, plain text.

Each parser returns an :class:`ExtractedText` dataclass: clean text plus
per-page structure for citations.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from agenticos_shared.errors import ValidationError


@dataclass
class ExtractedText:
    text: str
    pages: list[str] = field(default_factory=list)  # text per page (PDF)
    meta: dict[str, str] = field(default_factory=dict)


def _parse_pdf(blob: bytes) -> ExtractedText:
    from pypdf import PdfReader  # local import keeps cold start fast

    try:
        reader = PdfReader(io.BytesIO(blob))
    except Exception as exc:
        raise ValidationError(f"could not parse PDF: {exc}") from exc

    pages = []
    for page in reader.pages:
        try:
            pages.append((page.extract_text() or "").strip())
        except Exception:
            pages.append("")
    text = "\n\n".join(p for p in pages if p)
    meta = {"page_count": str(len(pages))}
    return ExtractedText(text=text, pages=pages, meta=meta)


def _parse_html(blob: bytes) -> ExtractedText:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(blob, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    return ExtractedText(text=text, meta={"title": title} if title else {})


def _parse_md(blob: bytes) -> ExtractedText:
    # Markdown is just text; we preserve it as-is. (We strip front-matter.)
    text = blob.decode("utf-8", "replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            text = text[end + 4 :]
    return ExtractedText(text=text.strip())


def _parse_plain(blob: bytes) -> ExtractedText:
    return ExtractedText(text=blob.decode("utf-8", "replace"))


def extract_text(
    *, blob: bytes, mime: str | None = None, filename: str | None = None
) -> ExtractedText:
    """Dispatch to a parser by MIME type or filename extension."""

    m = (mime or "").lower()
    name = (filename or "").lower()

    if "pdf" in m or name.endswith(".pdf"):
        return _parse_pdf(blob)
    if "html" in m or name.endswith((".html", ".htm")):
        return _parse_html(blob)
    if "markdown" in m or name.endswith((".md", ".markdown")):
        return _parse_md(blob)
    if "text" in m or name.endswith((".txt", ".log", ".csv", ".json")):
        return _parse_plain(blob)

    # Fallback — assume utf-8 text.
    return _parse_plain(blob)
