"""OpenAI tools for persistent semantic memory and preferences."""

from __future__ import annotations

from typing import Any

from ..memory.metadata_store import metadata_store
from ..memory.vector_store import vector_store


MEMORY_SAVE_TOOL = {
    "type": "function",
    "function": {
        "name": "memory_save",
        "description": "Persist a useful user preference, decision, or project fact in semantic memory.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
}
MEMORY_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "memory_search",
        "description": "Search persistent semantic memory for relevant prior context.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
PREFERENCE_UPDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "preference_update",
        "description": "Persist a user preference as a key/value setting.",
        "parameters": {
            "type": "object",
            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
            "required": ["key", "value"],
            "additionalProperties": False,
        },
    },
}


def memory_save(text: str) -> dict[str, Any]:
    return vector_store.add_memory(text)


def memory_search(query: str) -> dict[str, Any]:
    return vector_store.search_memory(query, limit=3)


def preference_update(key: str, value: str) -> dict[str, Any]:
    return metadata_store.update(key, value)
