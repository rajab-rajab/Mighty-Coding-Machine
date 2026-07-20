"""Code review specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.file_ops import FILE_LIST_TOOL, FILE_READ_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class ReviewAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Review Agent",
            system_prompt=(
                "You are the Review Agent for Coding Machine. Review code for correctness, security, "
                "maintainability, and testability. Prioritize concrete findings by severity."
            ),
            tools=(FILE_READ_TOOL, FILE_LIST_TOOL, CODEBASE_SEARCH_TOOL),
        )
