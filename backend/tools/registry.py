"""User-selectable built-in tool catalog for MCM agents."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .code_exec import RUN_CODE_TOOL, run_code
from .database import DB_CONNECT_TOOL, DB_EXECUTE_QUERY_TOOL, DB_LIST_TABLES_TOOL, db_connect, db_execute_query, db_list_tables
from .deployment import REQUEST_DEPLOYMENT_APPROVAL_TOOL, request_deployment_approval
from .diagnostics import ANALYZE_ERROR_TOOL, analyze_error
from .file_ops import FILE_LIST_TOOL, FILE_READ_TOOL, FILE_WRITE_TOOL, file_list, file_read, file_write
from .git_agent import GIT_ACTION_TOOL, GIT_DIFF_TOOL, GIT_HISTORY_TOOL, GIT_STATUS_TOOL, git_action, git_diff, git_history, git_status
from .memory import MEMORY_SAVE_TOOL, MEMORY_SEARCH_TOOL, PREFERENCE_UPDATE_TOOL, memory_save, memory_search, preference_update
from .planning import CREATE_PLAN_TOOL, create_plan
from .presentation import PRESENT_CODE_TOOL, present_code
from .project import SCAFFOLD_PROJECT_TOOL, scaffold_project
from .quality import (
    DEPENDENCY_MANIFEST_TOOL,
    PROJECT_INVENTORY_TOOL,
    PYTHON_SYNTAX_TOOL,
    WORKSPACE_SEARCH_TOOL,
    dependency_manifest,
    project_inventory,
    python_syntax_check,
    workspace_search,
)
from .rag import CODEBASE_SEARCH_TOOL, codebase_search
from .test_runner import RUN_TESTS_TOOL, run_tests


@dataclass(frozen=True)
class ToolDefinition:
    """One tool that can be explicitly added to an agent request."""

    id: str
    name: str
    description: str
    category: str
    risk: str
    schema: dict[str, Any]
    function: Callable[..., Any]

    def public(self) -> dict[str, str]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk": self.risk,
        }


class ToolRegistry:
    """Register and safely combine explicitly selected built-in tools."""

    def __init__(self) -> None:
        self.tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self.tools[tool.id] = tool

    def get(self, tool_id: str) -> ToolDefinition | None:
        return self.tools.get(tool_id)

    def public_definitions(self) -> list[dict[str, str]]:
        return [tool.public() for tool in self.tools.values()]

    def get_active_config(self, tool_ids: Iterable[str]) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        schemas: list[dict[str, Any]] = []
        functions: dict[str, Callable[..., Any]] = {}
        seen_names: set[str] = set()
        for tool_id in dict.fromkeys(str(tool_id) for tool_id in tool_ids):
            tool = self.get(tool_id)
            if tool is None:
                continue
            tool_name = str(tool.schema.get("function", {}).get("name", ""))
            if tool_name and tool_name not in seen_names:
                schemas.append(tool.schema)
                seen_names.add(tool_name)
            functions[tool_name] = tool.function
        return schemas, functions


def create_default_tool_registry() -> ToolRegistry:
    """Create the complete built-in tool catalog shown in the Chat Tools menu."""
    registry = ToolRegistry()
    for tool in (
        ToolDefinition("file-read", "File Read", "Read a UTF-8 file inside the active workspace.", "Workspace", "read", FILE_READ_TOOL, file_read),
        ToolDefinition("file-write", "File Write", "Write a file inside the workspace through the existing change-review flow.", "Workspace", "write", FILE_WRITE_TOOL, file_write),
        ToolDefinition("file-list", "File List", "List files and folders inside the workspace.", "Workspace", "read", FILE_LIST_TOOL, file_list),
        ToolDefinition("workspace-search", "Workspace Search", "Find exact text, paths, lines, and snippets in workspace files.", "Workspace", "read", WORKSPACE_SEARCH_TOOL, workspace_search),
        ToolDefinition("codebase-search", "Codebase Search", "Search indexed code semantically across the workspace.", "Search", "read", CODEBASE_SEARCH_TOOL, codebase_search),
        ToolDefinition("run-code", "Run Code", "Run supported Python or Node snippets with captured output.", "Execution", "execute", RUN_CODE_TOOL, run_code),
        ToolDefinition("present-code", "Present Code", "Present generated code or a diff to the desktop UI.", "Execution", "read", PRESENT_CODE_TOOL, present_code),
        ToolDefinition("analyze-error", "Analyze Error", "Analyze an error message and suggest likely debugging steps.", "Execution", "read", ANALYZE_ERROR_TOOL, analyze_error),
        ToolDefinition("scaffold-project", "Scaffold Project", "Create a workspace project structure from requested files.", "Workspace", "write", SCAFFOLD_PROJECT_TOOL, scaffold_project),
        ToolDefinition("db-connect", "Database Connect", "Connect to a configured SQLite, PostgreSQL, or MySQL database.", "Database", "connect", DB_CONNECT_TOOL, db_connect),
        ToolDefinition("db-list-tables", "Database List Tables", "Inspect tables in an active database connection.", "Database", "read", DB_LIST_TABLES_TOOL, db_list_tables),
        ToolDefinition("db-execute-query", "Database Execute Query", "Run a SQL query with existing safety and approval checks.", "Database", "write", DB_EXECUTE_QUERY_TOOL, db_execute_query),
        ToolDefinition("project-inventory", "Project Inventory", "Inspect files, languages, line counts, and project configuration.", "Quality", "read", PROJECT_INVENTORY_TOOL, project_inventory),
        ToolDefinition("dependency-manifest", "Dependency Manifest", "Inspect dependency manifest files without changing packages.", "Quality", "read", DEPENDENCY_MANIFEST_TOOL, dependency_manifest),
        ToolDefinition("python-syntax-check", "Python Syntax Check", "Parse a Python file and report syntax errors without running it.", "Quality", "read", PYTHON_SYNTAX_TOOL, python_syntax_check),
        ToolDefinition("run-tests", "Run Tests", "Run focused tests inside the workspace.", "Quality", "execute", RUN_TESTS_TOOL, run_tests),
        ToolDefinition("create-plan", "Create Plan", "Create and display a structured implementation plan.", "Planning", "read", CREATE_PLAN_TOOL, create_plan),
        ToolDefinition("git-status", "Git Status", "Inspect repository status for the active project.", "Source Control", "read", GIT_STATUS_TOOL, git_status),
        ToolDefinition("git-diff", "Git Diff", "Inspect file differences in the active project repository.", "Source Control", "read", GIT_DIFF_TOOL, git_diff),
        ToolDefinition("git-history", "Git History", "Read commit history for the active project repository.", "Source Control", "read", GIT_HISTORY_TOOL, git_history),
        ToolDefinition("git-action", "Git Action", "Run an approved source-control action such as stage, commit, push, or pull.", "Source Control", "approval", GIT_ACTION_TOOL, git_action),
        ToolDefinition("memory-save", "Memory Save", "Save a useful project fact or preference to persistent semantic memory.", "Memory", "write", MEMORY_SAVE_TOOL, memory_save),
        ToolDefinition("memory-search", "Memory Search", "Search persistent semantic memory for relevant context.", "Memory", "read", MEMORY_SEARCH_TOOL, memory_search),
        ToolDefinition("preference-update", "Preference Update", "Save a user preference as a persistent key/value setting.", "Memory", "write", PREFERENCE_UPDATE_TOOL, preference_update),
        ToolDefinition("request-deployment-approval", "Deployment Approval", "Request elevated user approval before a deployment operation.", "Deployment", "approval", REQUEST_DEPLOYMENT_APPROVAL_TOOL, request_deployment_approval),
    ):
        registry.register(tool)
    return registry


tool_registry = create_default_tool_registry()


__all__ = ["ToolDefinition", "ToolRegistry", "tool_registry"]
