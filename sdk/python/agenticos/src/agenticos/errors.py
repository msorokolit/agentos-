"""SDK exceptions."""

from __future__ import annotations

from typing import Any


class AgenticOSAPIError(Exception):
    """Raised when the AgenticOS API returns a non-2xx response."""

    def __init__(
        self,
        status: int,
        title: str | None = None,
        code: str | None = None,
        detail: str | None = None,
        body: Any | None = None,
    ) -> None:
        super().__init__(detail or title or f"HTTP {status}")
        self.status = status
        self.title = title
        self.code = code
        self.detail = detail
        self.body = body

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"AgenticOSAPIError(status={self.status}, code={self.code!r}, "
            f"title={self.title!r}, detail={self.detail!r})"
        )
