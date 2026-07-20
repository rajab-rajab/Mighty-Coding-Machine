"""Diagnostics tool for the debugging specialist."""

from __future__ import annotations

from typing import Any


ANALYZE_ERROR_TOOL = {
    "type": "function",
    "function": {
        "name": "analyze_error",
        "description": "Summarize an error and identify likely debugging clues.",
        "parameters": {
            "type": "object",
            "properties": {"error": {"type": "string"}, "context": {"type": "string", "default": ""}},
            "required": ["error"],
            "additionalProperties": False,
        },
    },
}
ANALYZE_ERROR_SCHEMA = ANALYZE_ERROR_TOOL


def analyze_error(error: str, context: str = "") -> dict[str, Any]:
    """Return lightweight, deterministic diagnostics for an error message."""
    error_text = str(error).strip()
    error_type = error_text.split(":", 1)[0] if ":" in error_text else "UnknownError"
    return {
        "success": True,
        "error_type": error_type.strip() or "UnknownError",
        "summary": error_text[:500],
        "context": context[:1000],
        "next_step": "Inspect the first traceback frame in the project code and reproduce the failure.",
    }
