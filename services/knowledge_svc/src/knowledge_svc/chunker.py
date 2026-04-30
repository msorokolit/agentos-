"""Token-aware chunker with overlap.

We use ``tiktoken``'s ``cl100k_base`` encoding as a stable approximation
for token counts across most local models; not exact for every tokenizer
but good enough for chunk sizing.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

_ENC = None


def _enc():
    global _ENC
    if _ENC is None:
        _ENC = tiktoken.get_encoding("cl100k_base")
    return _ENC


@dataclass
class Chunk:
    ord: int
    text: str
    token_count: int
    meta: dict[str, int | str] | None = None


def count_tokens(text: str) -> int:
    return len(_enc().encode(text))


def chunk_pages(
    pages: list[str],
    *,
    chunk_size: int = 400,
    overlap: int = 60,
    base_meta: dict[str, int | str] | None = None,
) -> list[Chunk]:
    """Like ``chunk_text`` but stamps every chunk's ``meta.page`` with a
    1-based page index. Useful for PDFs so citations can surface page
    numbers (PLAN §13 P3 acceptance).
    """

    out: list[Chunk] = []
    counter = 0
    for idx, page in enumerate(pages, start=1):
        if not page or not page.strip():
            continue
        page_meta: dict[str, int | str] = dict(base_meta or {})
        page_meta["page"] = idx
        for ch in chunk_text(
            page,
            chunk_size=chunk_size,
            overlap=overlap,
            base_meta=page_meta,
        ):
            out.append(
                Chunk(
                    ord=counter,
                    text=ch.text,
                    token_count=ch.token_count,
                    meta=ch.meta,
                )
            )
            counter += 1
    return out


def chunk_text(
    text: str,
    *,
    chunk_size: int = 400,
    overlap: int = 60,
    base_meta: dict[str, int | str] | None = None,
) -> list[Chunk]:
    """Split ``text`` into overlapping token-windows.

    Greedy, paragraph-aware: we first split on blank lines, then pack
    paragraphs into windows up to ``chunk_size`` tokens, with ``overlap``
    tokens carried into the next window.
    """

    if not text.strip():
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be in [0, chunk_size)")

    enc = _enc()
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    windows: list[list[int]] = []
    current: list[int] = []

    for para in paragraphs:
        toks = enc.encode(para + "\n\n")
        if not current:
            current = list(toks)
            continue
        if len(current) + len(toks) <= chunk_size:
            current.extend(toks)
        else:
            windows.append(current)
            # carry overlap tokens into the next window
            if overlap and len(current) > overlap:
                tail = current[-overlap:]
                current = list(tail) + list(toks)
            else:
                current = list(toks)

    if current:
        windows.append(current)

    # If a single paragraph blew past chunk_size, hard-split.
    final: list[list[int]] = []
    for w in windows:
        if len(w) <= chunk_size:
            final.append(w)
            continue
        i = 0
        while i < len(w):
            final.append(w[i : i + chunk_size])
            i += max(1, chunk_size - overlap)

    chunks: list[Chunk] = []
    for idx, toks in enumerate(final):
        text_piece = enc.decode(toks).strip()
        if not text_piece:
            continue
        chunks.append(
            Chunk(
                ord=idx,
                text=text_piece,
                token_count=len(toks),
                meta=dict(base_meta) if base_meta else None,
            )
        )
    return chunks
