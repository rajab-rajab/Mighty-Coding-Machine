"""Central approval workflow for actions that can change or publish user data."""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Iterator
from uuid import uuid4


class ApprovalLevel(StrEnum):
    AUTOMATIC = "automatic"
    CONFIRM = "confirm"
    ELEVATED = "elevated"


@dataclass
class PendingApproval:
    approval_id: str
    category: str
    action: str
    summary: str
    details: str
    level: ApprovalLevel
    owner_id: str
    cancel_event: threading.Event | None = None
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool | None = None
    rejection_reason: str = ""


_APPROVAL_OWNER: ContextVar[str] = ContextVar("approval_owner", default="")


@contextmanager
def approval_scope(owner_id: str) -> Iterator[None]:
    """Associate approval requests with the Socket.IO client that initiated them."""
    token = _APPROVAL_OWNER.set(str(owner_id or ""))
    try:
        yield
    finally:
        _APPROVAL_OWNER.reset(token)


def current_approval_owner() -> str:
    return _APPROVAL_OWNER.get()


def database_approval_level(query: str) -> ApprovalLevel:
    """Classify database statements without treating reads as dangerous writes."""
    normalized = re.sub(r"/\*.*?\*/|--[^\r\n]*", " ", str(query or ""), flags=re.DOTALL).strip().upper()
    if not normalized:
        return ApprovalLevel.AUTOMATIC
    if re.search(r"\b(DROP|TRUNCATE|ALTER|ATTACH|VACUUM|LOAD\s+EXTENSION)\b", normalized):
        return ApprovalLevel.ELEVATED
    if re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE|CREATE|REINDEX|GRANT|REVOKE)\b", normalized):
        return ApprovalLevel.CONFIRM
    return ApprovalLevel.AUTOMATIC


def shell_approval_level(command: str) -> ApprovalLevel:
    """Classify terminal commands; read-only and common run commands remain automatic."""
    normalized = str(command or "").strip().lower()
    if not normalized:
        return ApprovalLevel.AUTOMATIC
    if re.search(r"\b(del|erase|rmdir|rd|format|diskpart|shutdown|reg\s+(?:add|delete)|remove-item|set-content|clear-content)\b", normalized):
        return ApprovalLevel.ELEVATED
    if re.search(r"(?:>>?|\|\s*tee\b|\b(git\s+push|git\s+pull)\b|\b(powershell|cmd)\b)", normalized):
        return ApprovalLevel.CONFIRM
    if re.match(r"^(?:python(?:\.exe)?|py|node|npm\s+(?:test|run)|pytest|dir|ls|type|cat|echo|where|whoami|git\s+(?:status|diff|log|branch))\b", normalized):
        return ApprovalLevel.AUTOMATIC
    return ApprovalLevel.CONFIRM


class ApprovalManager:
    """Coordinate one-time user decisions for dangerous operations."""

    def __init__(self, timeout_seconds: float = 900.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._pending: dict[str, PendingApproval] = {}
        self._lock = threading.RLock()

    def request(
        self,
        category: str,
        action: str,
        summary: str,
        details: str,
        emit_event: Callable[[str, dict[str, Any]], None] | None,
        level: ApprovalLevel,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        if level == ApprovalLevel.AUTOMATIC:
            return {"approved": True, "level": level.value, "automatic": True}
        if emit_event is None:
            return {
                "approved": False,
                "level": level.value,
                "requires_approval": True,
                "message": "Ask the user for approval before continuing.",
            }

        approval_id = f"approval-{uuid4().hex}"
        pending = PendingApproval(
            approval_id=approval_id,
            category=str(category),
            action=str(action),
            summary=str(summary)[:500],
            details=str(details)[:4000],
            level=level,
            owner_id=current_approval_owner(),
            cancel_event=cancel_event,
        )
        with self._lock:
            self._pending[approval_id] = pending
        emit_event(
            "approval_required",
            {
                "approval_id": approval_id,
                "category": pending.category,
                "action": pending.action,
                "summary": pending.summary,
                "details": pending.details,
                "level": level.value,
                "confirmation_phrase": "APPROVE" if level == ApprovalLevel.ELEVATED else "",
            },
        )

        deadline = time.monotonic() + self.timeout_seconds
        while not pending.event.wait(0.25):
            if cancel_event is not None and cancel_event.is_set():
                self.resolve(approval_id, False, rejection_reason="Approval cancelled")
                break
            if time.monotonic() >= deadline:
                self.resolve(approval_id, False, rejection_reason="Approval timed out")
                break

        with self._lock:
            self._pending.pop(approval_id, None)
        if pending.approved is True:
            return {"approved": True, "level": level.value, "approval_id": approval_id}
        return {
            "approved": False,
            "level": level.value,
            "approval_id": approval_id,
            "requires_approval": True,
            "message": pending.rejection_reason or "Approval rejected.",
        }

    def resolve(
        self,
        approval_id: str,
        approved: bool,
        confirmation_text: str = "",
        owner_id: str | None = None,
        rejection_reason: str = "",
    ) -> bool:
        with self._lock:
            pending = self._pending.get(str(approval_id))
            if pending is None:
                return False
            requested_owner = current_approval_owner() if owner_id is None else str(owner_id)
            if pending.owner_id and pending.owner_id != requested_owner:
                return False
            if approved and pending.level == ApprovalLevel.ELEVATED and confirmation_text.strip().upper() != "APPROVE":
                return False
            pending.approved = bool(approved)
            pending.rejection_reason = rejection_reason or ("Approval rejected." if not approved else "")
            pending.event.set()
            return True

    def cancel_for(self, cancel_event: threading.Event) -> None:
        with self._lock:
            pending_ids = [
                approval_id
                for approval_id, pending in self._pending.items()
                if pending.cancel_event is cancel_event
            ]
        for approval_id in pending_ids:
            self.resolve(approval_id, False, rejection_reason="Approval cancelled")

    def cancel_owner(self, owner_id: str) -> None:
        with self._lock:
            pending_ids = [
                approval_id
                for approval_id, pending in self._pending.items()
                if pending.owner_id == str(owner_id)
            ]
        for approval_id in pending_ids:
            self.resolve(approval_id, False, owner_id=owner_id, rejection_reason="Client disconnected")


approval_manager = ApprovalManager()
