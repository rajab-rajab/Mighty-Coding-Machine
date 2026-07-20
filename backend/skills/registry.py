"""Dynamic skill definitions and registry for Coding Machine agents."""

from __future__ import annotations

from typing import Any, Callable, List, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..tools.code_exec import RUN_CODE_TOOL, run_code
from ..tools.database import (
    DB_CONNECT_TOOL,
    DB_EXECUTE_QUERY_TOOL,
    DB_LIST_TABLES_TOOL,
    db_connect,
    db_execute_query,
    db_list_tables,
)
from ..tools.deployment import REQUEST_DEPLOYMENT_APPROVAL_TOOL, request_deployment_approval
from ..tools.diagnostics import ANALYZE_ERROR_TOOL, analyze_error
from ..tools.file_ops import (
    FILE_LIST_TOOL,
    FILE_READ_TOOL,
    FILE_WRITE_TOOL,
    file_list,
    file_read,
    file_write,
)
from ..tools.git_agent import (
    GIT_ACTION_TOOL,
    GIT_DIFF_TOOL,
    GIT_HISTORY_TOOL,
    GIT_STATUS_TOOL,
    git_action,
    git_diff,
    git_history,
    git_status,
)
from ..tools.planning import CREATE_PLAN_TOOL, create_plan
from ..tools.quality import (
    DEPENDENCY_MANIFEST_TOOL,
    PROJECT_INVENTORY_TOOL,
    PYTHON_SYNTAX_TOOL,
    WORKSPACE_SEARCH_TOOL,
    dependency_manifest,
    project_inventory,
    python_syntax_check,
    workspace_search,
)
from ..tools.rag import CODEBASE_SEARCH_TOOL, codebase_search
from ..tools.test_runner import RUN_TESTS_TOOL, run_tests


class SkillDefinition(BaseModel):
    """Configuration injected into an agent for one user-selectable skill."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    description: str
    category: Literal[
        "language",
        "database",
        "quality",
        "security",
        "source-control",
        "deployment",
        "productivity",
    ]
    icon: str
    system_prompt_extension: str
    tool_schemas: List[dict] = Field(default_factory=list)
    tool_functions: dict[str, Callable[..., Any]] = Field(default_factory=dict)


class SkillRegistry:
    """Register skills and combine selected skill configuration on demand."""

    def __init__(self) -> None:
        self.skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        self.skills[skill.id] = skill

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self.skills.get(skill_id)

    def list(self) -> list[SkillDefinition]:
        return list(self.skills.values())

    def get_active_config(self, skill_ids: List[str]) -> tuple[str, list[dict], dict[str, Callable[..., Any]]]:
        """Combine prompt extensions, unique schemas, and functions for selected IDs."""
        combined_prompt = ""
        combined_schemas: list[dict] = []
        combined_functions: dict[str, Callable[..., Any]] = {}
        seen_tool_names: set[str] = set()

        for skill_id in dict.fromkeys(skill_ids):
            skill = self.skills.get(skill_id)
            if skill is None:
                continue
            if skill.system_prompt_extension:
                combined_prompt += skill.system_prompt_extension.rstrip() + "\n"
            for schema in skill.tool_schemas:
                tool_name = schema.get("function", {}).get("name") if isinstance(schema, dict) else None
                if tool_name is None or tool_name not in seen_tool_names:
                    combined_schemas.append(schema)
                    if tool_name:
                        seen_tool_names.add(tool_name)
            combined_functions.update(skill.tool_functions)

        return combined_prompt, combined_schemas, combined_functions

    def public_definitions(self) -> list[dict[str, str]]:
        """Return frontend-safe metadata without schemas or callable objects."""
        return [
            {
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "category": skill.category,
                "icon": skill.icon,
            }
            for skill in self.skills.values()
        ]


def create_default_registry() -> SkillRegistry:
    """Create the built-in skills available to the initial UI."""
    registry = SkillRegistry()
    registry.register(
        SkillDefinition(
            id="python",
            name="Python",
            description="Python coding, execution, and debugging guidance.",
            category="language",
            icon="🐍",
            system_prompt_extension=(
                "The Python skill is active. Prefer idiomatic Python 3.14, explicit types, small testable "
                "functions, and run focused Python checks before presenting a solution."
            ),
            tool_schemas=[RUN_CODE_TOOL],
            tool_functions={"run_code": run_code},
        )
    )
    registry.register(
        SkillDefinition(
            id="javascript",
            name="JavaScript",
            description="JavaScript and Node.js implementation guidance.",
            category="language",
            icon="JS",
            system_prompt_extension=(
                "The JavaScript skill is active. Prefer modern, readable JavaScript, use Node.js for local "
                "checks when available, and call out browser-versus-server assumptions."
            ),
            tool_schemas=[RUN_CODE_TOOL],
            tool_functions={"run_code": run_code},
        )
    )

    def register_workspace_language(
        skill_id: str,
        name: str,
        description: str,
        icon: str,
        guidance: str,
    ) -> None:
        registry.register(
            SkillDefinition(
                id=skill_id,
                name=name,
                description=description,
                category="language",
                icon=icon,
                system_prompt_extension=(
                    f"The {name} skill is active. {guidance} Inspect the existing workspace before editing, "
                    "preserve explicit user constraints, keep implementation idiomatic, and use the available "
                    "workspace tools to verify relevant files before completing the task."
                ),
                tool_schemas=[FILE_READ_TOOL, FILE_WRITE_TOOL, FILE_LIST_TOOL, WORKSPACE_SEARCH_TOOL],
                tool_functions={
                    "file_read": file_read,
                    "file_write": file_write,
                    "file_list": file_list,
                    "workspace_search": workspace_search,
                },
            )
        )

    for language in (
        (
            "typescript",
            "TypeScript",
            "Type-safe TypeScript design, implementation, and maintenance.",
            "TS",
            "Prefer strict types, clear module boundaries, and safe browser-versus-server assumptions.",
        ),
        (
            "html-css",
            "HTML & CSS",
            "Accessible semantic HTML and maintainable responsive CSS.",
            "</>",
            "Use semantic, accessible markup and responsive CSS that respects the existing visual design.",
        ),
        (
            "java",
            "Java",
            "Modern Java application design and implementation guidance.",
            "J",
            "Prefer clear packages, explicit error handling, and maintainable object-oriented design.",
        ),
        (
            "csharp",
            "C#",
            "Modern C# and .NET application development guidance.",
            "C#",
            "Use current .NET conventions, nullable-aware types, async APIs where appropriate, and clean project structure.",
        ),
        (
            "c-cpp",
            "C / C++",
            "Safe C and modern C++ systems-programming guidance.",
            "C++",
            "Prefer RAII and standard-library facilities in C++, validate memory ownership, and avoid undefined behavior.",
        ),
        (
            "go",
            "Go",
            "Idiomatic Go services, command-line tools, and concurrent programs.",
            "Go",
            "Prefer small packages, explicit errors, context-aware concurrency, and gofmt-compatible code.",
        ),
        (
            "rust",
            "Rust",
            "Safe, idiomatic Rust application and systems development.",
            "Rs",
            "Respect ownership and borrowing, use Result-based error handling, and keep APIs idiomatic and testable.",
        ),
        (
            "php",
            "PHP",
            "Modern PHP web and backend development guidance.",
            "PHP",
            "Use modern PHP syntax, strict types when compatible, secure input handling, and clear framework boundaries.",
        ),
        (
            "ruby",
            "Ruby",
            "Idiomatic Ruby and Rails-oriented development guidance.",
            "Rb",
            "Favor readable Ruby, conventional structure, secure parameter handling, and focused tests.",
        ),
        (
            "kotlin",
            "Kotlin",
            "Modern Kotlin application and Android development guidance.",
            "Kt",
            "Use null-safe types, concise idioms, coroutines where appropriate, and clear separation of concerns.",
        ),
        (
            "swift",
            "Swift",
            "Modern Swift application and Apple-platform development guidance.",
            "Sw",
            "Use value semantics, safe optionals, structured concurrency where appropriate, and platform conventions.",
        ),
    ):
        register_workspace_language(*language)

    registry.register(
        SkillDefinition(
            id="sqlite",
            name="SQLite",
            description="SQLite schema design, queries, and data debugging.",
            category="database",
            icon="▣",
            system_prompt_extension=(
                "The SQLite skill is active. Inspect tables before modifying data, use parameterized SQL "
                "when values are dynamic, and explain migration and transaction considerations."
            ),
            tool_schemas=[DB_CONNECT_TOOL, DB_LIST_TABLES_TOOL, DB_EXECUTE_QUERY_TOOL],
            tool_functions={
                "db_connect": db_connect,
                "db_list_tables": db_list_tables,
                "db_execute_query": db_execute_query,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="database-engineering",
            name="Database Engineering",
            description="Design and operate SQLite, PostgreSQL, and MySQL schemas and queries safely.",
            category="database",
            icon="◫",
            system_prompt_extension=(
                "The Database Engineering skill is active. Identify the database dialect, inspect schemas before "
                "changes, use parameterized queries for dynamic values, and explain transaction, migration, and "
                "rollback considerations. Ask for confirmation before destructive database operations."
            ),
            tool_schemas=[DB_CONNECT_TOOL, DB_LIST_TABLES_TOOL, DB_EXECUTE_QUERY_TOOL],
            tool_functions={
                "db_connect": db_connect,
                "db_list_tables": db_list_tables,
                "db_execute_query": db_execute_query,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="backend-api",
            name="Backend API Engineering",
            description="Design maintainable Python web APIs with validation, errors, and observability.",
            category="language",
            icon="⚙",
            system_prompt_extension=(
                "The Backend API Engineering skill is active. Preserve API contracts, validate inputs at boundaries, "
                "return consistent errors, avoid blocking work in request handlers, and include focused tests for "
                "success and failure paths."
            ),
            tool_schemas=[FILE_READ_TOOL, FILE_WRITE_TOOL, RUN_CODE_TOOL, PYTHON_SYNTAX_TOOL, WORKSPACE_SEARCH_TOOL],
            tool_functions={
                "file_read": file_read,
                "file_write": file_write,
                "run_code": run_code,
                "python_syntax_check": python_syntax_check,
                "workspace_search": workspace_search,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="frontend-ui",
            name="Frontend UI Engineering",
            description="Build accessible, responsive browser interfaces with disciplined state and event handling.",
            category="language",
            icon="◈",
            system_prompt_extension=(
                "The Frontend UI Engineering skill is active. Preserve the existing layout, use semantic accessible "
                "controls, keep state transitions explicit, avoid blocking the main thread, and verify keyboard, "
                "loading, error, and empty states before presenting UI changes."
            ),
            tool_schemas=[FILE_READ_TOOL, FILE_WRITE_TOOL, FILE_LIST_TOOL, WORKSPACE_SEARCH_TOOL],
            tool_functions={
                "file_read": file_read,
                "file_write": file_write,
                "file_list": file_list,
                "workspace_search": workspace_search,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="testing-quality",
            name="Testing and Quality",
            description="Inspect projects, validate Python syntax, and run focused tests before completion.",
            category="quality",
            icon="✓",
            system_prompt_extension=(
                "The Testing and Quality skill is active. Start with the smallest relevant checks, preserve existing "
                "tests, report failures precisely, and never claim a check passed without its output. Prefer syntax "
                "validation and targeted tests before broader suites."
            ),
            tool_schemas=[PROJECT_INVENTORY_TOOL, PYTHON_SYNTAX_TOOL, RUN_TESTS_TOOL, WORKSPACE_SEARCH_TOOL],
            tool_functions={
                "project_inventory": project_inventory,
                "python_syntax_check": python_syntax_check,
                "run_tests": run_tests,
                "workspace_search": workspace_search,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="debugging",
            name="Debugging and Diagnostics",
            description="Reproduce failures, inspect evidence, and apply the smallest verified fix.",
            category="quality",
            icon="◉",
            system_prompt_extension=(
                "The Debugging and Diagnostics skill is active. Reproduce the problem when safe, inspect the "
                "relevant files and error output, isolate the root cause, and make the smallest targeted change. "
                "Validate the fix with a focused check and distinguish evidence from assumptions."
            ),
            tool_schemas=[FILE_READ_TOOL, RUN_CODE_TOOL, ANALYZE_ERROR_TOOL, PYTHON_SYNTAX_TOOL, WORKSPACE_SEARCH_TOOL],
            tool_functions={
                "file_read": file_read,
                "run_code": run_code,
                "analyze_error": analyze_error,
                "python_syntax_check": python_syntax_check,
                "workspace_search": workspace_search,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="security-audit",
            name="Security Audit",
            description="Review workspace code, dependencies, and boundaries for common security risks.",
            category="security",
            icon="盾",
            system_prompt_extension=(
                "The Security Audit skill is active. Treat workspace boundaries, secrets, subprocesses, SQL, and "
                "dependency manifests as security-sensitive. Prefer evidence from inspected files, identify severity "
                "and remediation, and do not make destructive changes without approval."
            ),
            tool_schemas=[PROJECT_INVENTORY_TOOL, WORKSPACE_SEARCH_TOOL, DEPENDENCY_MANIFEST_TOOL, FILE_READ_TOOL],
            tool_functions={
                "project_inventory": project_inventory,
                "workspace_search": workspace_search,
                "dependency_manifest": dependency_manifest,
                "file_read": file_read,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="git-workflow",
            name="Git Workflow",
            description="Inspect repository state and perform approved, scoped source-control actions.",
            category="source-control",
            icon="⑂",
            system_prompt_extension=(
                "The Git Workflow skill is active. Inspect status and diff before writes, keep commits focused, "
                "never discard user changes silently, and require approval for staging, commits, branch changes, "
                "pulls, or pushes."
            ),
            tool_schemas=[GIT_STATUS_TOOL, GIT_DIFF_TOOL, GIT_HISTORY_TOOL, GIT_ACTION_TOOL],
            tool_functions={
                "git_status": git_status,
                "git_diff": git_diff,
                "git_history": git_history,
                "git_action": git_action,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="windows-packaging",
            name="Windows Packaging",
            description="Prepare distributable Windows builds with explicit artifact and runtime checks.",
            category="deployment",
            icon="▣",
            system_prompt_extension=(
                "The Windows Packaging skill is active. Preserve onedir packaging, verify bundled assets and writable "
                "runtime paths, report build artifacts explicitly, and request approval before any release or deploy "
                "operation."
            ),
            tool_schemas=[PROJECT_INVENTORY_TOOL, DEPENDENCY_MANIFEST_TOOL, REQUEST_DEPLOYMENT_APPROVAL_TOOL],
            tool_functions={
                "project_inventory": project_inventory,
                "dependency_manifest": dependency_manifest,
                "request_deployment_approval": request_deployment_approval,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="documentation",
            name="Documentation",
            description="Create accurate user and developer documentation from the current project state.",
            category="productivity",
            icon="▤",
            system_prompt_extension=(
                "The Documentation skill is active. Inspect the implementation before documenting it, distinguish "
                "verified behavior from recommendations, keep setup steps reproducible, and avoid inventing features."
            ),
            tool_schemas=[FILE_READ_TOOL, FILE_LIST_TOOL, WORKSPACE_SEARCH_TOOL, PROJECT_INVENTORY_TOOL],
            tool_functions={
                "file_read": file_read,
                "file_list": file_list,
                "workspace_search": workspace_search,
                "project_inventory": project_inventory,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="requirements-planning",
            name="Requirements and Planning",
            description="Convert complex requests into scoped, testable implementation plans.",
            category="productivity",
            icon="☷",
            system_prompt_extension=(
                "The Requirements and Planning skill is active. Preserve every explicit requirement, identify "
                "constraints and acceptance criteria, inspect the existing project before proposing changes, and "
                "produce a concise ordered plan with risks and verification steps."
            ),
            tool_schemas=[CREATE_PLAN_TOOL, PROJECT_INVENTORY_TOOL, WORKSPACE_SEARCH_TOOL],
            tool_functions={
                "create_plan": create_plan,
                "project_inventory": project_inventory,
                "workspace_search": workspace_search,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="performance-diagnostics",
            name="Performance Diagnostics",
            description="Measure likely bottlenecks from project structure and diagnose runtime issues methodically.",
            category="quality",
            icon="◒",
            system_prompt_extension=(
                "The Performance Diagnostics skill is active. Establish a baseline, isolate the slow boundary, "
                "prefer measurement over speculation, and preserve correctness while proposing optimizations."
            ),
            tool_schemas=[PROJECT_INVENTORY_TOOL, WORKSPACE_SEARCH_TOOL, PYTHON_SYNTAX_TOOL, FILE_READ_TOOL],
            tool_functions={
                "project_inventory": project_inventory,
                "workspace_search": workspace_search,
                "python_syntax_check": python_syntax_check,
                "file_read": file_read,
            },
        )
    )
    registry.register(
        SkillDefinition(
            id="codebase-rag",
            name="Codebase RAG",
            description="Use semantic and exact search together before changing an existing codebase.",
            category="productivity",
            icon="⌕",
            system_prompt_extension=(
                "The Codebase RAG skill is active. Search semantic context and exact references before editing, "
                "compare nearby patterns, and cite the relevant workspace paths in your reasoning."
            ),
            tool_schemas=[CODEBASE_SEARCH_TOOL, WORKSPACE_SEARCH_TOOL, PROJECT_INVENTORY_TOOL],
            tool_functions={
                "codebase_search": codebase_search,
                "workspace_search": workspace_search,
                "project_inventory": project_inventory,
            },
        )
    )
    return registry


skill_registry = create_default_registry()
