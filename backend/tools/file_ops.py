"""Workspace-confined file tools exposed to the coding agents."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

from ..config import WORKSPACE_PATH
from ..security import validate_path


FILE_READ_TOOL = {
    "type": "function",
    "function": {
        "name": "file_read",
        "description": "Read a UTF-8 text file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Workspace-relative file path."}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}
FILE_READ_SCHEMA = FILE_READ_TOOL

FILE_WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "file_write",
        "description": "Write UTF-8 text to a file inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Workspace-relative file path."},
                "content": {"type": "string", "description": "Complete file content."},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
}
FILE_WRITE_SCHEMA = FILE_WRITE_TOOL

FILE_LIST_TOOL = {
    "type": "function",
    "function": {
        "name": "file_list",
        "description": "List files and directories inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Workspace-relative directory path."}},
            "required": [],
            "additionalProperties": False,
        },
    },
}
FILE_LIST_SCHEMA = FILE_LIST_TOOL


_ACTIVE_PROJECT_PATH: ContextVar[str] = ContextVar("active_project_path", default="")


def get_active_project_path() -> str:
    """Return the current request's workspace-relative project path."""
    return _ACTIVE_PROJECT_PATH.get()


@contextmanager
def project_scope(relative_path: str | None) -> Iterator[None]:
    """Scope relative agent paths to one project for the current thread."""
    value = str(relative_path or "").replace("\\", "/").strip("/")
    token = _ACTIVE_PROJECT_PATH.set(value)
    try:
        yield
    finally:
        _ACTIVE_PROJECT_PATH.reset(token)


def _scoped_path(path: str | Path) -> str | Path:
    project_path = get_active_project_path()
    if not project_path:
        return path
    raw_path = str(path).replace("\\", "/")
    if raw_path.lower().startswith("workspace/"):
        raw_path = raw_path[len("workspace/") :]
    if Path(raw_path).is_absolute() or raw_path == project_path or raw_path.startswith(f"{project_path}/"):
        return raw_path
    return f"{project_path}/{raw_path.lstrip('./')}"


def resolve_workspace_path(path: str | Path) -> Path:
    """Resolve a path and reject anything outside ``WORKSPACE_PATH``."""
    return Path(validate_path(_scoped_path(path), WORKSPACE_PATH))


def file_read(path: str) -> dict[str, Any]:
    """Read a text file within the configured workspace."""
    try:
        target = resolve_workspace_path(path)
        if not target.is_file():
            return {"success": False, "error": f"File not found: {path}"}
        return {"success": True, "path": target.relative_to(WORKSPACE_PATH).as_posix(), "content": target.read_text(encoding="utf-8")}
    except (OSError, UnicodeError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}


def file_write(path: str, content: str) -> dict[str, Any]:
    """Write a text file within the configured workspace."""
    try:
        target = resolve_workspace_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"success": True, "path": target.relative_to(WORKSPACE_PATH).as_posix(), "bytes_written": len(content.encode("utf-8"))}
    except (OSError, TypeError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}


def file_list(path: str = ".") -> dict[str, Any]:
    """List one workspace directory without following paths outside it."""
    try:
        target = resolve_workspace_path(path)
        if not target.is_dir():
            return {"success": False, "error": f"Directory not found: {path}"}
        entries = [
            {"name": item.name, "type": "directory" if item.is_dir() else "file"}
            for item in sorted(target.iterdir(), key=lambda item: item.name.lower())
        ]
        return {"success": True, "path": target.relative_to(WORKSPACE_PATH).as_posix(), "entries": entries}
    except (OSError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}
