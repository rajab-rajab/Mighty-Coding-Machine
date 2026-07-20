"""Conditional Git and source-control specialist."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.git_agent import GIT_ACTION_TOOL, GIT_DIFF_TOOL, GIT_HISTORY_TOOL, GIT_STATUS_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class GitAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Git Agent",
            system_prompt=(
                "You are the Git Agent for Coding Machine. Handle explicit repository operations such as status, "
                "diffs, branches, commits, push, and pull. Inspect status and diffs before writes. All write and "
                "remote operations require user approval through git_action; never bypass that gate."
            ),
            tools=(GIT_STATUS_TOOL, GIT_DIFF_TOOL, GIT_HISTORY_TOOL, GIT_ACTION_TOOL, CODEBASE_SEARCH_TOOL),
        )
