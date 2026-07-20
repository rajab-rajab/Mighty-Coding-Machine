"""Conditional security auditing and release-gate specialist."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.diagnostics import ANALYZE_ERROR_TOOL
from ..tools.file_ops import FILE_LIST_TOOL, FILE_READ_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class SecurityAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Security Agent",
            system_prompt=(
                "You are the Security Agent for Coding Machine. Audit security-sensitive or release-bound work. "
                "Inspect paths, permissions, secrets, authentication, injection risks, subprocesses, database "
                "writes, approvals, and dependency exposure. Report concrete findings by severity and do not modify "
                "files unless the user explicitly requests a reviewed fix."
            ),
            tools=(FILE_READ_TOOL, FILE_LIST_TOOL, ANALYZE_ERROR_TOOL, CODEBASE_SEARCH_TOOL),
        )
