from __future__ import annotations

import sys
from pathlib import Path

from backend.mcp.client_manager import MCPClientManager, classify_mcp_tool
from backend.mcp.presets import builtin_server_configs


class AutoApprove:
    def request(self, **kwargs):
        return {"approved": True, "level": kwargs["level"].value}


def test_mcp_tool_classification_is_conservative():
    assert classify_mcp_tool("workspace_read_file")[0] == "read"
    assert classify_mcp_tool("git_commit")[0] == "write"
    assert classify_mcp_tool("run_shell_command")[1].value == "elevated"
    assert classify_mcp_tool("db_execute_query")[0] == "database"


def test_builtin_mcp_servers_are_disabled_by_default():
    servers = builtin_server_configs()
    assert {server.server_id for server in servers} == {
        "fetch",
        "git",
        "github",
        "codex_cli_bridge",
        "openai_remote",
    }
    assert all(not server.enabled for server in servers)
    assert all(server.read_only for server in servers)
    assert next(server for server in servers if server.server_id == "fetch").timeout_seconds == 90.0


def test_http_server_requires_a_valid_url(tmp_path: Path):
    manager = MCPClientManager(approvals=AutoApprove(), log_path=tmp_path / "mcp.log")
    try:
        manager.configure({"server_id": "remote", "transport": "streamable_http", "enabled": True, "url": "not-a-url"})
    except ValueError as exc:
        assert "http(s) URL" in str(exc)
    else:
        raise AssertionError("Invalid MCP URL was accepted")


def test_task_group_startup_error_is_reported_with_actionable_details(tmp_path: Path):
    manager = MCPClientManager(approvals=AutoApprove(), log_path=tmp_path / "mcp.log")
    config = next(server for server in builtin_server_configs() if server.server_id == "fetch")

    message = manager._connection_error(config, ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("server exited")]))

    assert "TaskGroup" not in message
    assert "server exited" in message
    assert "try Connect again" in message


def test_stdio_environment_does_not_inject_application_pythonpath(tmp_path: Path, monkeypatch):
    manager = MCPClientManager(approvals=AutoApprove(), log_path=tmp_path / "mcp.log")
    config = next(server for server in builtin_server_configs() if server.server_id == "fetch")
    monkeypatch.delenv("PYTHONPATH", raising=False)

    environment = manager._stdio_environment(config)

    assert "PYTHONPATH" not in environment


def test_manager_discovers_stdio_tools_and_blocks_read_only_writes(tmp_path: Path):
    project_root = Path(__file__).resolve().parents[2]
    manager = MCPClientManager(approvals=AutoApprove(), log_path=tmp_path / "mcp.log")
    manager.configure(
        {
            "server_id": "cm",
            "name": "CM test server",
            "command": sys.executable,
            "args": ["app.py", "--mcp-server"],
            "cwd": str(project_root),
            "enabled": True,
            "read_only": True,
        }
    )
    try:
        connected = manager.connect("cm")
        assert connected["success"] is True
        assert {tool["name"] for tool in connected["tools"]} >= {"workspace_info", "workspace_write_file"}

        schemas, functions = manager.agent_tool_definitions()
        function_names = {schema["function"]["name"] for schema in schemas}
        assert "mcp_cm_workspace_info" in function_names
        assert "mcp_cm_workspace_write_file" not in function_names
        assert functions["mcp_cm_workspace_info"]()["success"] is True

        info = manager.call_tool("cm", "workspace_info", {})
        assert info["success"] is True
        blocked = manager.call_tool("cm", "workspace_write_file", {"relative_path": "blocked.txt", "content": "no"})
        assert blocked["blocked"] is True
        assert not (project_root / "workspace" / "blocked.txt").exists()
        assert (tmp_path / "mcp.log").exists()
    finally:
        assert manager.disconnect("cm")["success"] is True
