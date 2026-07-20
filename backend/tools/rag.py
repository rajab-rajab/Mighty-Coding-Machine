"""OpenAI function tool for semantic codebase search."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..rag.indexer import workspace_indexer


CODEBASE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "codebase_search",
        "description": "Search the indexed workspace for relevant code and configuration snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "file_types": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}


def codebase_search(query: str, file_types: Iterable[str] | None = None) -> dict[str, Any]:
    return workspace_indexer.search_codebase(query, file_types=file_types)
