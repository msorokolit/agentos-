"""Document ingestion pipeline.

* :func:`extract_text` dispatches to a parser based on MIME / extension.
* Parsers return plain text + optional per-page metadata.
"""

from .parsers import ExtractedText, extract_text

__all__ = ["ExtractedText", "extract_text"]
