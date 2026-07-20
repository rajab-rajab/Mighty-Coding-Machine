"""Debugging specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.code_exec import RUN_CODE_TOOL
from ..tools.diagnostics import ANALYZE_ERROR_TOOL
from ..tools.file_ops import FILE_READ_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class DebugAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Debug Agent",
            system_prompt=(
                "You are the Debug Agent for Coding Machine. Reproduce failures when possible, "
                "trace errors to their root cause, and propose the smallest safe fix."
            ),
            tools=(FILE_READ_TOOL, RUN_CODE_TOOL, ANALYZE_ERROR_TOOL, CODEBASE_SEARCH_TOOL),
        )
