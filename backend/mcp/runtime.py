"""Shared MCP client manager used by Flask and the agent runtime."""

from .client_manager import MCPClientManager
from .presets import builtin_server_configs


mcp_client_manager = MCPClientManager(builtin_server_configs())


__all__ = ["mcp_client_manager"]
