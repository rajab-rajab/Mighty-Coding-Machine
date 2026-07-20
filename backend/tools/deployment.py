"""Approval gate for deployment adapters added by future integrations."""

from __future__ import annotations

import threading
from typing import Any, Callable

from ..approval import ApprovalLevel, approval_manager


REQUEST_DEPLOYMENT_APPROVAL_TOOL = {
    "type": "function",
    "function": {
        "name": "request_deployment_approval",
        "description": "Request elevated user approval before a deployment or release action.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Deployment target, such as staging or production."},
                "details": {"type": "string", "description": "Exact deployment operation and affected artifacts."},
            },
            "required": ["target", "details"],
            "additionalProperties": False,
        },
    },
}
REQUEST_DEPLOYMENT_APPROVAL_SCHEMA = REQUEST_DEPLOYMENT_APPROVAL_TOOL


def request_deployment_approval(
    target: str,
    details: str,
    emit_event: Callable[[str, dict[str, Any]], None] | None,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    """Require elevated typed approval before a deployment adapter executes."""
    return approval_manager.request(
        category="deployment",
        action="deploy_project",
        summary=f"Deploy project to {str(target)[:240]}",
        details=details,
        emit_event=emit_event,
        level=ApprovalLevel.ELEVATED,
        cancel_event=cancel_event,
    )
