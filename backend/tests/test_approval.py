from __future__ import annotations

import threading
import time

from backend.approval import (
    ApprovalLevel,
    ApprovalManager,
    approval_scope,
    database_approval_level,
    shell_approval_level,
)
from backend.tools.deployment import request_deployment_approval


def test_action_levels_distinguish_safe_confirm_and_elevated():
    assert database_approval_level("SELECT * FROM users") == ApprovalLevel.AUTOMATIC
    assert database_approval_level("INSERT INTO users(name) VALUES ('CM')") == ApprovalLevel.CONFIRM
    assert database_approval_level("DROP TABLE users") == ApprovalLevel.ELEVATED
    assert shell_approval_level("python main.py") == ApprovalLevel.AUTOMATIC
    assert shell_approval_level("git push origin main") == ApprovalLevel.CONFIRM
    assert shell_approval_level("del C:\\Windows\\Temp\\file.tmp") == ApprovalLevel.ELEVATED


def test_elevated_approval_requires_owner_and_phrase():
    manager = ApprovalManager(timeout_seconds=2)
    events = []
    result = {}

    def wait_for_approval():
        with approval_scope("client-a"):
            result.update(
                manager.request(
                    category="deployment",
                    action="deploy_project",
                    summary="Deploy CM",
                    details="production",
                    emit_event=lambda event, payload: events.append((event, payload)),
                    level=ApprovalLevel.ELEVATED,
                )
            )

    thread = threading.Thread(target=wait_for_approval)
    thread.start()
    deadline = time.monotonic() + 1
    while not events and time.monotonic() < deadline:
        time.sleep(0.01)

    approval_id = events[0][1]["approval_id"]
    assert manager.resolve(approval_id, True, confirmation_text="APPROVE", owner_id="client-b") is False
    assert manager.resolve(approval_id, True, confirmation_text="yes", owner_id="client-a") is False
    assert manager.resolve(approval_id, True, confirmation_text="APPROVE", owner_id="client-a") is True
    thread.join(timeout=1)

    assert result["approved"] is True
    assert result["level"] == "elevated"


def test_deployment_gate_never_auto_approves():
    result = request_deployment_approval("production", "release", emit_event=None)

    assert result["approved"] is False
    assert result["requires_approval"] is True
    assert result["level"] == "elevated"
