"""Built-in tools shipped with AgenticOS.

Built-ins live in this package and are registered by name. The registry
introspects this module's ``BUILTINS`` dict to resolve invokers for
``kind=="builtin"`` rows.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .http_get import http_get
from .rag_search import rag_search

# Async (ctx, args) -> dict
BuiltinFn = Callable[[dict[str, Any], dict[str, Any]], Awaitable[dict[str, Any]]]


BUILTINS: dict[str, BuiltinFn] = {
    "http_get": http_get,
    "rag_search": rag_search,
}


def builtin_descriptors() -> list[dict[str, Any]]:
    """JSON-Schema descriptors for every built-in. Used to seed the registry."""

    return [
        {
            "name": "http_get",
            "description": "Fetch a URL with HTTP GET. Subject to egress allow-list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                    "headers": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
                "required": ["url"],
            },
        },
        {
            "name": "rag_search",
            "description": "Search a workspace's documents via hybrid retrieval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
                    "collection_id": {"type": "string", "format": "uuid"},
                },
                "required": ["query"],
            },
        },
    ]


__all__ = ["BUILTINS", "BuiltinFn", "builtin_descriptors"]
