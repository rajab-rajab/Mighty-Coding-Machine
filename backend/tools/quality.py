"""Read-only workspace quality and diagnostics tools.

These tools deliberately inspect project state without installing packages,
changing files, or invoking a shell. They are safe to expose through selected
quality, security, and documentation skills.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Iterable

from ..config import WORKSPACE_PATH
from ..security import validate_path


_IGNORED_DIRECTORIES = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv"}
_MANIFEST_NAMES = {
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "setup.py",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
}
_MAX_FILE_BYTES = 1_000_000


PROJECT_INVENTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "project_inventory",
        "description": "Inspect project files, languages, line counts, and common configuration files without modifying anything.",
        "parameters": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Workspace-relative project directory."},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 1000},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

WORKSPACE_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "workspace_search",
        "description": "Search workspace text for an exact string and return file paths, lines, and snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
                "relative_path": {"type": "string", "description": "Optional workspace-relative directory."},
                "file_types": {"type": "array", "items": {"type": "string"}},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

DEPENDENCY_MANIFEST_TOOL = {
    "type": "function",
    "function": {
        "name": "dependency_manifest",
        "description": "Read dependency manifest files in a project without installing or changing dependencies.",
        "parameters": {
            "type": "object",
            "properties": {
                "relative_path": {"type": "string", "description": "Workspace-relative project directory."},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}

PYTHON_SYNTAX_TOOL = {
    "type": "function",
    "function": {
        "name": "python_syntax_check",
        "description": "Parse one workspace Python file and report syntax errors without executing it.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}


def _root(relative_path: str | None) -> Path:
    return Path(validate_path(relative_path or ".", WORKSPACE_PATH))


def _iter_files(root: Path, max_files: int = 1000) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    yielded = 0
    for path in sorted(root.rglob("*")):
        if yielded >= max_files:
            return
        if any(part in _IGNORED_DIRECTORIES for part in path.parts):
            continue
        if path.is_file():
            yielded += 1
            yield path


def project_inventory(relative_path: str = "", max_files: int = 1000) -> dict[str, Any]:
    """Return a compact inventory of a workspace project."""
    try:
        root = _root(relative_path)
        if not root.exists():
            return {"success": False, "error": f"Path does not exist: {relative_path or '.'}"}
        files: list[dict[str, Any]] = []
        extensions: dict[str, int] = {}
        total_lines = 0
        for path in _iter_files(root, max(1, min(int(max_files), 5000))):
            relative = path.relative_to(WORKSPACE_PATH).as_posix()
            entry: dict[str, Any] = {"path": relative, "bytes": path.stat().st_size}
            extension = path.suffix.lower() or "[no extension]"
            extensions[extension] = extensions.get(extension, 0) + 1
            if path.stat().st_size <= _MAX_FILE_BYTES:
                try:
                    line_count = len(path.read_text(encoding="utf-8").splitlines())
                    entry["lines"] = line_count
                    total_lines += line_count
                except (OSError, UnicodeDecodeError):
                    entry["binary_or_unreadable"] = True
            else:
                entry["large_file"] = True
            files.append(entry)
        manifest_paths = [path["path"] for path in files if Path(path["path"]).name in _MANIFEST_NAMES]
        return {
            "success": True,
            "root": root.relative_to(WORKSPACE_PATH).as_posix() if root != WORKSPACE_PATH else ".",
            "files": files,
            "file_count": len(files),
            "total_lines": total_lines,
            "extensions": extensions,
            "manifests": manifest_paths,
            "truncated": len(files) >= max(1, min(int(max_files), 5000)),
        }
    except (OSError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}


def workspace_search(
    query: str,
    relative_path: str = "",
    file_types: list[str] | None = None,
    max_results: int = 50,
) -> dict[str, Any]:
    """Search readable workspace text while staying inside the workspace root."""
    if not isinstance(query, str) or not query.strip():
        return {"success": False, "error": "Search query is required."}
    try:
        root = _root(relative_path)
        normalized_types = {str(value).lower() for value in (file_types or []) if str(value).strip()}
        if normalized_types:
            normalized_types = {value if value.startswith(".") else f".{value}" for value in normalized_types}
        results: list[dict[str, Any]] = []
        for path in _iter_files(root, 5000):
            if normalized_types and path.suffix.lower() not in normalized_types:
                continue
            try:
                if path.stat().st_size > _MAX_FILE_BYTES:
                    continue
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for line_number, line in enumerate(lines, 1):
                if query.casefold() in line.casefold():
                    results.append(
                        {
                            "path": path.relative_to(WORKSPACE_PATH).as_posix(),
                            "line": line_number,
                            "snippet": line.strip()[:500],
                        }
                    )
                    if len(results) >= max(1, min(int(max_results), 100)):
                        return {"success": True, "query": query, "results": results, "truncated": True}
        return {"success": True, "query": query, "results": results, "truncated": False}
    except (OSError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}


def dependency_manifest(relative_path: str = "") -> dict[str, Any]:
    """Collect known dependency manifests and lightweight parsed metadata."""
    try:
        root = _root(relative_path)
        manifests: list[dict[str, Any]] = []
        for path in _iter_files(root, 5000):
            if path.name not in _MANIFEST_NAMES or path.stat().st_size > _MAX_FILE_BYTES:
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            item: dict[str, Any] = {
                "path": path.relative_to(WORKSPACE_PATH).as_posix(),
                "bytes": len(content.encode("utf-8")),
            }
            if path.name == "package.json":
                try:
                    package = json.loads(content)
                    item["dependencies"] = package.get("dependencies", {})
                    item["dev_dependencies"] = package.get("devDependencies", {})
                except json.JSONDecodeError:
                    item["parse_error"] = "Invalid JSON"
            else:
                item["lines"] = content.splitlines()[:200]
            manifests.append(item)
        return {"success": True, "manifests": manifests, "count": len(manifests)}
    except (OSError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}


def python_syntax_check(path: str) -> dict[str, Any]:
    """Parse a Python file without executing it."""
    try:
        target = Path(validate_path(path, WORKSPACE_PATH))
        if not target.is_file():
            return {"success": False, "error": f"Python file does not exist: {path}"}
        source = target.read_text(encoding="utf-8")
        ast.parse(source, filename=str(target))
        return {"success": True, "path": target.relative_to(WORKSPACE_PATH).as_posix(), "valid": True}
    except SyntaxError as exc:
        return {
            "success": True,
            "path": path,
            "valid": False,
            "error": exc.msg,
            "line": exc.lineno,
            "column": exc.offset,
        }
    except (OSError, UnicodeDecodeError, ValueError, PermissionError) as exc:
        return {"success": False, "error": str(exc)}

