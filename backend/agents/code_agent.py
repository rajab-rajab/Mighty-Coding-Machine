"""Coding specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.code_exec import RUN_CODE_TOOL
from ..tools.file_ops import FILE_READ_TOOL, FILE_WRITE_TOOL
from ..tools.presentation import PRESENT_CODE_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class CodeAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Code Agent",
            system_prompt=(
                "You are the Code Agent for Coding Machine. Write clear, maintainable code, "
                "You MUST search the codebase before creating or editing files to ensure consistency. "
                "Inspect relevant files before editing, and explain important implementation choices. "
                "Use file_write for changes, run_code for focused checks, and present_code when code "
                "or a diff should be shown to the user."
            ),
            tools=(FILE_READ_TOOL, FILE_WRITE_TOOL, RUN_CODE_TOOL, PRESENT_CODE_TOOL, CODEBASE_SEARCH_TOOL),
        )
