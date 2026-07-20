"""Local code execution tool used by coding and debugging agents."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

from ..security import build_python_sandbox_source, validate_code_execution
from .file_ops import get_active_project_path, resolve_workspace_path
from ..config import WORKSPACE_PATH


RUN_CODE_TOOL = {
    "type": "function",
    "function": {
        "name": "run_code",
        "description": "Run Python or Node.js code in the workspace and capture output.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Source code to execute."},
                "language": {"type": "string", "enum": ["python", "node"], "default": "python"},
                "timeout": {"type": "integer", "minimum": 1, "maximum": 120, "default": 30},
            },
            "required": ["code"],
            "additionalProperties": False,
        },
    },
}
RUN_CODE_SCHEMA = RUN_CODE_TOOL


def run_code(code: str, language: str = "python", timeout: int = 30) -> dict[str, Any]:
    """Execute source code with a bounded timeout and captured output."""
    validation = validate_code_execution(code, language)
    if not validation.get("allowed"):
        return {"success": False, "error": validation["reason"], "language": language}
    if language == "python":
        command = [sys.executable, "-c", build_python_sandbox_source(code, WORKSPACE_PATH)]
    elif language == "node":
        node = shutil.which("node")
        if node is None:
            return {"success": False, "error": "Node.js executable was not found on PATH"}
        command = [node, "-e", code]
    else:
        return {"success": False, "error": f"Unsupported language: {language}"}

    try:
        active_project = get_active_project_path()
        working_directory = resolve_workspace_path(active_project) if active_project else WORKSPACE_PATH
        process = subprocess.Popen(
            command,
            cwd=working_directory,
            env={**__import__("os").environ, "CM_WORKSPACE_ROOT": str(WORKSPACE_PATH)},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=max(1, min(int(timeout), 120)))
        except subprocess.TimeoutExpired as exc:
            process.kill()
            stdout, stderr = process.communicate()
            return {
                "success": False,
                "returncode": process.returncode,
                "stdout": stdout or exc.stdout or "",
                "stderr": stderr or exc.stderr or "",
                "error": "Code execution timed out",
                "language": language,
            }
        return {
            "success": process.returncode == 0,
            "returncode": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "language": language,
        }
    except OSError as exc:
        return {"success": False, "error": str(exc), "language": language}
