"""Tool for sending generated code and diffs to the frontend."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


PRESENT_CODE_TOOL = {
    "type": "function",
    "function": {
        "name": "present_code",
        "description": "Present code or a code diff to the user in the editor.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Complete code to present."},
                "diff": {"type": "string", "description": "Unified diff or explanation of changes."},
                "language": {"type": "string", "default": "text"},
                "filename": {"type": "string", "default": ""},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}
PRESENT_CODE_SCHEMA = PRESENT_CODE_TOOL


def present_code(
    code: str,
    diff: str = "",
    language: str = "text",
    filename: str = "",
    emit_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Emit a ``code_presentation`` event and return its payload."""
    payload = {"code": code, "diff": diff, "language": language, "filename": filename}

    if emit_event is None:
        from ..server import socketio

        socketio.emit("code_presentation", payload)
    else:
        emit_event("code_presentation", payload)

    return {"success": True, "presented": True, "filename": filename}
