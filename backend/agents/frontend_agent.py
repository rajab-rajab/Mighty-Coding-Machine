"""Conditional frontend and UI specialist."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.file_ops import FILE_READ_TOOL, FILE_WRITE_TOOL
from ..tools.presentation import PRESENT_CODE_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class FrontendAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Frontend Agent",
            system_prompt=(
                "You are the Frontend Agent for Coding Machine. Work only on explicitly requested UI surfaces. "
                "Inspect existing HTML, CSS, JavaScript, accessibility, responsive behavior, and state bindings "
                "before editing. Preserve the current layout and avoid introducing unnecessary frameworks."
            ),
            tools=(FILE_READ_TOOL, FILE_WRITE_TOOL, PRESENT_CODE_TOOL, CODEBASE_SEARCH_TOOL),
        )
