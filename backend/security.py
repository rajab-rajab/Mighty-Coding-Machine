"""Centralized validation for workspace paths and SQL operations."""

from __future__ import annotations

import os
import re
import ast
from pathlib import Path
from typing import Any

from .exceptions import PathTraversalError


_BLOCKED_IMPORT_PREFIXES = (
    "subprocess",
    "ctypes",
    "cffi",
    "winreg",
    "_winapi",
    "win32",
)
_BLOCKED_CALLS = {
    "system",
    "popen",
    "spawn",
    "spawnl",
    "spawnlp",
    "spawnv",
    "spawnvp",
    "execv",
    "execve",
    "execl",
    "execlp",
    "execle",
    "execlpe",
    "execvp",
    "execvpe",
    "startfile",
    "__import__",
    "eval",
    "exec",
    "compile",
}
_BLOCKED_PATH_PATTERNS = (
    re.compile(r"(?i)(?:[a-z]:[\\/]|\\\\[^\\/]+[\\/]+[^\\/]+)"),
    re.compile(r"(?i)(?:%systemroot%|%windir%|\\windows(?:\\|/)|/etc(?:/|\\)|/usr(?:/|\\)|/bin(?:/|\\))"),
    re.compile(r"(?i)(?:\\system32(?:\\|/)|/system32(?:/|\\)|program files)"),
)
_BLOCKED_COMMAND_PATTERNS = (
    re.compile(r"(?i)(?:\brmdir\b|\bdel\b|\berase\b|\bformat(?:\.com)?\b|\bdiskpart\b)"),
    re.compile(r"(?i)(?:\bpowershell(?:\.exe)?\b|\bcmd(?:\.exe)?\b|\brm\s+-rf\b|\bsudo\b)"),
)


def _blocked_reason(reason: str) -> dict[str, Any]:
    return {"allowed": False, "reason": f"Agent execution blocked by security policy: {reason}"}


def validate_code_execution(code: str, language: str = "python") -> dict[str, Any]:
    """Preflight agent source before it reaches a local subprocess."""
    if not isinstance(code, str) or not code.strip():
        return _blocked_reason("source code is empty")
    normalized_language = str(language or "python").strip().lower()
    for pattern in _BLOCKED_PATH_PATTERNS:
        if pattern.search(code):
            return _blocked_reason("system or absolute file paths are not permitted")
    for pattern in _BLOCKED_COMMAND_PATTERNS:
        if pattern.search(code):
            return _blocked_reason("system or destructive shell commands are not permitted")

    if normalized_language == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return _blocked_reason(f"invalid Python source: {exc.msg}")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [node.module or ""]
            else:
                imported = []
            for module in imported:
                if any(module == prefix or module.startswith(prefix + ".") for prefix in _BLOCKED_IMPORT_PREFIXES):
                    return _blocked_reason(f"the {module} module can launch unrestricted processes")
            if isinstance(node, ast.Call):
                function_name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
                if function_name in _BLOCKED_CALLS:
                    return _blocked_reason(f"the {function_name} operation is not permitted")
        return {"allowed": True}

    if normalized_language == "node":
        if re.search(r"(?i)(?:\brequire\s*\(|\bimport\s+|\bimport\s*\()", code):
            return _blocked_reason("Node module loading is not permitted for agent snippets")
        if re.search(r"(?i)(?:require\s*\(\s*['\"](?:fs|fs/promises|child_process|worker_threads)|from\s+['\"](?:fs|fs/promises|child_process))", code):
            return _blocked_reason("Node filesystem and process-control modules are not permitted")
        if re.search(r"(?i)(?:process\s*\.\s*(?:binding|dlopen|mainModule|getBuiltinModule)|module\s*\.\s*constructor|\b(?:eval|Function)\s*\()", code):
            return _blocked_reason("Node runtime escape operations are not permitted")
        if re.search(r"(?i)\.(?:unlink|unlinkSync|rm|rmSync|rmdir|rmdirSync|rename|renameSync)\s*\(", code):
            return _blocked_reason("Node filesystem deletion and rename operations are not permitted")
        return {"allowed": True}

    return _blocked_reason(f"unsupported execution language: {language}")


def build_python_sandbox_source(
    code: str,
    workspace_root: str | os.PathLike[str],
    temp_root: str | os.PathLike[str] | None = None,
    prelude: str = "",
) -> str:
    """Wrap agent Python in an audit hook that confines mutations to safe roots."""
    workspace = str(Path(workspace_root).resolve())
    temporary = str(Path(temp_root or os.getenv("TEMP", ".")).resolve())
    return f'''
import os as _cm_os
import sys as _cm_sys
from pathlib import Path as _cm_Path

_CM_SAFE_ROOTS = (_cm_Path({workspace!r}), _cm_Path({temporary!r}))
_CM_BLOCKED_IMPORTS = {tuple(_BLOCKED_IMPORT_PREFIXES)!r}
{prelude}

def _cm_is_safe_path(value):
    if isinstance(value, bytes):
        value = _cm_os.fsdecode(value)
    if not isinstance(value, (str, _cm_os.PathLike)):
        return False
    try:
        raw_value = _cm_os.fspath(value)
        if isinstance(raw_value, str) and _cm_os.path.splitdrive(raw_value)[0] and not _cm_os.path.isabs(raw_value):
            return False
        candidate = _cm_Path(_cm_os.path.realpath(raw_value)).resolve()
        return any(candidate == root or root in candidate.parents for root in _CM_SAFE_ROOTS)
    except (OSError, ValueError, TypeError):
        return False

def _cm_audit(event, args):
    if event == "import":
        module = str(args[0] or "") if args else ""
        if module != "subprocess" and any(module == prefix or module.startswith(prefix + ".") for prefix in _CM_BLOCKED_IMPORTS):
            raise PermissionError("Agent security policy blocked a process or native-system import")
    if event in {{"subprocess.Popen", "os.system", "os.spawn", "pty.spawn"}}:
        raise PermissionError("Agent security policy blocked process creation")
    if event in {{"os.remove", "os.unlink", "os.rmdir", "os.rename", "os.replace", "shutil.rmtree", "shutil.move", "os.truncate", "os.chmod", "os.chown"}}:
        target = args[0] if args else None
        directory_fd = args[1] if event in {{"os.remove", "os.unlink", "os.rmdir", "os.rename", "os.replace"}} and len(args) > 1 else None
        if directory_fd not in (None, -1) or not _cm_is_safe_path(target):
            raise PermissionError("Agent security policy blocked a filesystem mutation outside the workspace")
    if event in {{"open", "os.open"}} and args:
        target = args[0]
        mode = args[1] if event == "open" and len(args) > 1 and isinstance(args[1], str) else ""
        flags = args[2] if event == "open" and len(args) > 2 and isinstance(args[2], int) else (args[1] if event == "os.open" and len(args) > 1 and isinstance(args[1], int) else 0)
        writes = any(flag in mode for flag in ("w", "a", "x", "+")) or bool(flags & (_cm_os.O_WRONLY | _cm_os.O_RDWR | _cm_os.O_CREAT | _cm_os.O_TRUNC | _cm_os.O_APPEND))
        if writes and not _cm_is_safe_path(target):
            raise PermissionError("Agent security policy blocked a write outside the workspace")
    if event == "os.mkdir" and args and not _cm_is_safe_path(args[0]):
        raise PermissionError("Agent security policy blocked directory creation outside the workspace")

_cm_sys.addaudithook(_cm_audit)
exec(compile({code!r}, "<cm-agent>", "exec"), dict(globals(), __name__="__main__", __file__="<cm-agent>"))
'''


def validate_path(relative_path: str | os.PathLike[str], workspace_root: str | os.PathLike[str]) -> str:
    """Resolve a workspace path and reject traversal outside its root."""
    if not isinstance(relative_path, (str, os.PathLike)):
        raise ValueError("Invalid workspace path")
    raw_path = os.fspath(relative_path)
    if "\x00" in raw_path:
        raise ValueError("Invalid workspace path")

    root = os.path.abspath(os.path.normpath(os.fspath(workspace_root)))
    candidate = os.path.abspath(os.path.normpath(os.path.join(root, raw_path)))
    root_prefix = root if root.endswith(os.sep) else root + os.sep
    if candidate != root and not candidate.startswith(root_prefix):
        raise PathTraversalError("Path traversal detected")

    real_root = os.path.realpath(root)
    real_candidate = os.path.realpath(candidate)
    real_prefix = real_root if real_root.endswith(os.sep) else real_root + os.sep
    if real_candidate != real_root and not real_candidate.startswith(real_prefix):
        raise PathTraversalError("Path traversal detected")
    return candidate


def validate_sql_query(query: str, workspace_root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Identify SQL statements that require explicit user confirmation."""
    if not isinstance(query, str) or not query.strip():
        return {"requires_confirmation": False}

    statements = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", query, flags=re.DOTALL).split(";")
    for statement in statements:
        normalized = statement.strip().upper()
        attach_match = re.search(r"\bATTACH\s+(?:DATABASE\s+)?['\"]([^'\"]+)['\"]", statement, flags=re.IGNORECASE)
        vacuum_match = re.search(r"\bVACUUM\s+INTO\s+['\"]([^'\"]+)['\"]", statement, flags=re.IGNORECASE)
        file_target = attach_match or vacuum_match
        if re.search(r"\b(?:ATTACH|VACUUM\s+INTO)\b", normalized) and not file_target:
            return {
                "requires_confirmation": False,
                "blocked": True,
                "reason": "Dynamic database file targets cannot be verified as workspace-local.",
            }
        if file_target:
            target = file_target.group(1)
            if workspace_root is not None and target != ":memory:":
                try:
                    validate_path(target, workspace_root)
                except (PathTraversalError, ValueError):
                    return {
                        "requires_confirmation": False,
                        "blocked": True,
                        "reason": "Database file targets must remain inside the workspace.",
                    }
            return {
                "requires_confirmation": True,
                "reason": "Query writes or attaches a database file.",
            }
        if re.search(r"\b(?:LOAD\s+EXTENSION|COPY\s+.*\bPROGRAM)\b", normalized, flags=re.DOTALL):
            return {
                "requires_confirmation": False,
                "blocked": True,
                "reason": "Database extension loading and operating-system program execution are blocked.",
            }
        if re.search(r"\b(DROP|ALTER|TRUNCATE)\b", normalized):
            return {
                "requires_confirmation": True,
                "reason": "Query modifies schema or deletes data.",
            }
        for keyword in ("DELETE", "UPDATE"):
            match = re.search(rf"\b{keyword}\b", normalized)
            if match and not re.search(r"\bWHERE\b", normalized[match.end() :]):
                return {
                    "requires_confirmation": True,
                    "reason": "Query modifies schema or deletes data.",
                }
    return {"requires_confirmation": False}
