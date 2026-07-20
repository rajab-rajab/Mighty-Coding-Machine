"""Reversible approval flow for agent-generated workspace changes."""

from __future__ import annotations

import difflib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .config import WORKSPACE_PATH
from .tools.file_ops import file_write, resolve_workspace_path


@dataclass
class PendingChange:
    review_id: str
    path: str
    content: str
    before_content: str
    before_exists: bool
    event: threading.Event = field(default_factory=threading.Event)
    accepted: bool | None = None
    cancel_event: threading.Event | None = None


class ChangeReviewManager:
    """Coordinate explicit user approval before an agent writes a file."""

    def __init__(self, timeout_seconds: float = 900.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._pending: dict[str, PendingChange] = {}
        self._lock = threading.RLock()

    def request(
        self,
        path: str,
        content: str,
        emit_event: Callable[[str, dict[str, Any]], None],
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        target = resolve_workspace_path(path)
        relative_path = target.relative_to(WORKSPACE_PATH).as_posix()
        before_exists = target.is_file()
        before_content = target.read_text(encoding="utf-8") if before_exists else ""
        review_id = f"review-{uuid4().hex}"
        pending = PendingChange(review_id, relative_path, content, before_content, before_exists, cancel_event=cancel_event)
        diff = "".join(
            difflib.unified_diff(
                before_content.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
            )
        )
        with self._lock:
            self._pending[review_id] = pending
        emit_event(
            "code_diff_review",
            {
                "review_id": review_id,
                "path": relative_path,
                "before": before_content,
                "after": content,
                "diff": diff,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        deadline = time.monotonic() + self.timeout_seconds
        while not pending.event.wait(0.25):
            if cancel_event is not None and cancel_event.is_set():
                self.resolve(review_id, False)
                break
            if time.monotonic() >= deadline:
                self.resolve(review_id, False)
                break

        with self._lock:
            self._pending.pop(review_id, None)
        if pending.accepted is not True:
            return {"success": False, "path": relative_path, "error": "Change rejected or review cancelled", "rejected": True}
        return file_write(relative_path, content)

    def resolve(self, review_id: str, accepted: bool) -> bool:
        with self._lock:
            pending = self._pending.get(review_id)
            if pending is None:
                return False
            pending.accepted = bool(accepted)
            pending.event.set()
            return True

    def cancel_all(self) -> None:
        with self._lock:
            pending_ids = list(self._pending)
        for review_id in pending_ids:
            self.resolve(review_id, False)

    def cancel_for(self, cancel_event: threading.Event) -> None:
        with self._lock:
            pending_ids = [
                review_id
                for review_id, pending in self._pending.items()
                if pending.cancel_event is cancel_event
            ]
        for review_id in pending_ids:
            self.resolve(review_id, False)


change_review_manager = ChangeReviewManager()
