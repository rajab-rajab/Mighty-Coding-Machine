"""Approval-aware Git tools for the conditional Git Agent."""

from __future__ import annotations

import threading
from typing import Any, Callable

from ..approval import ApprovalLevel, approval_manager
from .source_control import source_control


GIT_STATUS_TOOL = {
    "type": "function",
    "function": {
        "name": "git_status",
        "description": "Read repository status, branch, and staged/unstaged changes.",
        "parameters": {"type": "object", "properties": {"project_path": {"type": "string", "default": ""}}, "additionalProperties": False},
    },
}
GIT_DIFF_TOOL = {
    "type": "function",
    "function": {
        "name": "git_diff",
        "description": "Read a scoped Git diff for a workspace file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "default": ""},
                "staged": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
}
GIT_HISTORY_TOOL = {
    "type": "function",
    "function": {
        "name": "git_history",
        "description": "Read recent repository commit history.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "default": ""},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
            },
            "additionalProperties": False,
        },
    },
}
GIT_ACTION_TOOL = {
    "type": "function",
    "function": {
        "name": "git_action",
        "description": "Request approval and then perform one scoped Git write or remote operation.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["initialize", "switch_branch", "push", "pull", "stage", "unstage", "commit"]},
                "project_path": {"type": "string", "default": ""},
                "path": {"type": "string", "default": ""},
                "branch": {"type": "string", "default": ""},
                "remote": {"type": "string", "default": "origin"},
                "message": {"type": "string", "default": ""},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}


def git_status(project_path: str = "") -> dict[str, Any]:
    return source_control.status(project_path)


def git_diff(path: str = "", staged: bool = False) -> dict[str, Any]:
    return source_control.diff(path, staged)


def git_history(project_path: str = "", limit: int = 25) -> dict[str, Any]:
    return source_control.history(project_path, limit)


def git_action(
    action: str,
    project_path: str = "",
    path: str = "",
    branch: str = "",
    remote: str = "origin",
    message: str = "",
    emit_event: Callable[[str, dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    if cancel_event is not None and cancel_event.is_set():
        return {"success": False, "cancelled": True, "error": "Git action cancelled."}
    approval = approval_manager.request(
        category="source_control",
        action=f"git_{action}",
        summary=f"Approve Git action: {action}",
        details=f"Project: {project_path}\nPath: {path}\nBranch: {branch}\nRemote: {remote}\nMessage: {message}",
        emit_event=emit_event,
        level=ApprovalLevel.CONFIRM,
        cancel_event=cancel_event,
    )
    if not approval.get("approved"):
        return {"success": False, "requires_approval": True, **approval}
    actions = {
        "initialize": lambda: source_control.init(project_path),
        "switch_branch": lambda: source_control.switch_branch(branch, project_path),
        "push": lambda: source_control.push(remote, branch, project_path),
        "pull": lambda: source_control.pull(remote, branch, project_path),
        "stage": lambda: source_control.stage(path),
        "unstage": lambda: source_control.unstage(path),
        "commit": lambda: source_control.commit(message),
    }
    operation = actions.get(str(action))
    if operation is None:
        return {"success": False, "error": "Unsupported Git action."}
    return operation()
