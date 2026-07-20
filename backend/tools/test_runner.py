"""Safe project test execution for the Test Agent."""

from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path
from typing import Any

from ..config import WORKSPACE_PATH
from ..security import build_python_sandbox_source
from .file_ops import get_active_project_path, resolve_workspace_path


RUN_TESTS_TOOL = {
    "type": "function",
    "function": {
        "name": "run_tests",
        "description": "Run pytest tests inside the active workspace project and capture the result.",
        "parameters": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "default": 120},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
}


def run_tests(paths: list[str] | None = None, timeout: int = 120) -> dict[str, Any]:
    """Run pytest without shell execution and restrict targets to the active project."""
    active_project = get_active_project_path()
    base_path = resolve_workspace_path(active_project) if active_project else WORKSPACE_PATH
    requested_paths = paths or ["."]
    command_paths: list[str] = []
    try:
        for requested_path in requested_paths:
            raw_path = str(requested_path).replace("\\", "/")
            if not raw_path or raw_path.startswith("-"):
                return {"success": False, "error": "Invalid test path."}
            target = resolve_workspace_path(
                f"{active_project}/{raw_path}" if active_project and not Path(raw_path).is_absolute() else raw_path
            )
            target.relative_to(base_path)
            command_paths.append(target.relative_to(base_path).as_posix() or ".")
    except (OSError, PermissionError, ValueError) as exc:
        return {"success": False, "error": f"Test path is outside the active project: {exc}"}

    command = [
        sys.executable,
        "-c",
        build_python_sandbox_source(
            f"raise SystemExit(_cm_pytest.main({command_paths!r} + ['-q', '-p', 'no:capture', '-p', 'no:logging', '-p', 'no:cacheprovider']))",
            WORKSPACE_PATH,
            prelude="import pytest as _cm_pytest",
        ),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=str(base_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, min(int(timeout), 300)),
            check=False,
            shell=False,
            env={**os.environ, "CM_WORKSPACE_ROOT": str(WORKSPACE_PATH)},
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "timed_out": True,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "error": "Test execution timed out",
        }
    except OSError as exc:
        return {"success": False, "error": str(exc)}

    return {
        "success": completed.returncode == 0,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "no_tests": completed.returncode == 5,
    }
