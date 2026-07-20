"""Project scaffolding tool for the project specialist."""

from __future__ import annotations

from typing import Any

from .file_ops import file_write


SCAFFOLD_PROJECT_TOOL = {
    "type": "function",
    "function": {
        "name": "scaffold_project",
        "description": "Create a set of files for a new project inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "files": {
                    "type": "object",
                    "description": "Map of workspace-relative paths to file contents.",
                    "additionalProperties": {"type": "string"},
                }
            },
            "required": ["files"],
            "additionalProperties": False,
        },
    },
}
SCAFFOLD_PROJECT_SCHEMA = SCAFFOLD_PROJECT_TOOL


def scaffold_project(files: dict[str, str]) -> dict[str, Any]:
    """Write the requested project files using the confined file tool."""
    results = {path: file_write(path, content) for path, content in files.items()}
    return {"success": all(result.get("success") for result in results.values()), "files": results}
