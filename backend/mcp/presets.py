"""Opt-in configurations for official or locally hosted MCP servers."""

from __future__ import annotations

import sys

from ..config import PROJECT_DIR, WORKSPACE_PATH
from .client_manager import MCPServerConfig


def builtin_server_configs() -> list[MCPServerConfig]:
    """Return safe, disabled-by-default server presets.

    CM does not install these runtimes. Install the server runtime you choose
    (for example ``uvx`` or ``npx``), then configure and explicitly connect it.
    """
    return [
        MCPServerConfig(
            server_id="fetch",
            name="Official Fetch MCP Server",
            command="uvx",
            args=("mcp-server-fetch",),
            enabled=False,
            read_only=True,
            timeout_seconds=90.0,
        ),
        MCPServerConfig(
            server_id="git",
            name="Official Git MCP Server",
            command="uvx",
            args=("mcp-server-git", "--repository", str(WORKSPACE_PATH)),
            cwd=str(PROJECT_DIR),
            enabled=False,
            read_only=True,
        ),
        MCPServerConfig(
            server_id="github",
            name="Official GitHub MCP Server",
            command="npx",
            args=("-y", "@modelcontextprotocol/server-github"),
            env_keys=("GITHUB_PERSONAL_ACCESS_TOKEN",),
            cwd=str(PROJECT_DIR),
            enabled=False,
            read_only=True,
        ),
        MCPServerConfig(
            server_id="codex_cli_bridge",
            name="Mighty Coding Machine MCP Server (MCM CLI bridge)",
            command=sys.executable,
            args=("--mcp-server",) if getattr(sys, "frozen", False) else ("-m", "backend.mcp.server"),
            cwd=str(PROJECT_DIR),
            enabled=False,
            read_only=True,
        ),
        MCPServerConfig(
            server_id="openai_remote",
            name="OpenAI-compatible Remote MCP Server",
            transport="streamable_http",
            enabled=False,
            read_only=True,
        ),
    ]


__all__ = ["builtin_server_configs"]
