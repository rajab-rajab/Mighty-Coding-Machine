"""Project scaffolding specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.file_ops import FILE_WRITE_TOOL
from ..tools.project import SCAFFOLD_PROJECT_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class ProjectAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Project Agent",
            system_prompt=(
                "You are the Project Agent for Coding Machine. Turn requirements into a practical "
                "project structure, create only the files needed, and explain how to run the result."
            ),
            tools=(FILE_WRITE_TOOL, SCAFFOLD_PROJECT_TOOL, CODEBASE_SEARCH_TOOL),
        )
