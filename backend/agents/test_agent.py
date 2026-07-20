"""Testing and verification specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.code_exec import RUN_CODE_TOOL
from ..tools.file_ops import FILE_LIST_TOOL, FILE_READ_TOOL, FILE_WRITE_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL
from ..tools.test_runner import RUN_TESTS_TOOL


class TestAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Test Agent",
            system_prompt=(
                "You are the Test Agent for Coding Machine. Verify completed implementation work against "
                "the user's requirements and the active plan. Search and inspect the codebase first. "
                "Create focused pytest tests when coverage is missing, then run them with run_tests. "
                "Report exact failures and outputs. If a test fails, hand off to Debug Agent with the "
                "failure details; if all tests pass, hand off to Review Agent for final quality review. "
                "Do not claim success without executing relevant tests."
            ),
            tools=(
                FILE_READ_TOOL,
                FILE_LIST_TOOL,
                FILE_WRITE_TOOL,
                RUN_CODE_TOOL,
                RUN_TESTS_TOOL,
                CODEBASE_SEARCH_TOOL,
            ),
        )
