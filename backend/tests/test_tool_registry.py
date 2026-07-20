from __future__ import annotations

from backend.agents.orchestrator import get_agent_config
from backend.tools.registry import tool_registry


def test_tool_registry_lists_all_supported_built_in_tools():
    definitions = tool_registry.public_definitions()
    tool_ids = {tool["id"] for tool in definitions}

    assert len(definitions) == 25
    assert {
        "file-read",
        "file-write",
        "workspace-search",
        "db-execute-query",
        "run-tests",
        "git-action",
        "memory-save",
        "request-deployment-approval",
    } <= tool_ids


def test_selected_tools_are_added_to_agent_configuration():
    config = get_agent_config("Review Agent", active_tools=["memory-search", "project-inventory"])
    tool_names = {tool["function"]["name"] for tool in config.tools}

    assert {"memory_search", "project_inventory"} <= tool_names
    assert {"memory_search", "project_inventory"} <= config.tool_functions.keys()
