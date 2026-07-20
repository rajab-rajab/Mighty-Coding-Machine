"""Database specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.database import DB_CONNECT_TOOL, DB_EXECUTE_QUERY_TOOL, DB_LIST_TABLES_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class DatabaseAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Database Agent",
            system_prompt=(
                "You are the Database Agent for Coding Machine. Inspect schemas before changing data, "
                "write safe SQL, and clearly report query results and assumptions."
            ),
            tools=(DB_CONNECT_TOOL, DB_LIST_TABLES_TOOL, DB_EXECUTE_QUERY_TOOL, CODEBASE_SEARCH_TOOL),
        )
