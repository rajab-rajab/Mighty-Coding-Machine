"""Secure, optional MCP server for Coding Machine workspace capabilities.

The server uses stdio only so an MCP host starts and owns the process. Read and
search tools are available by default. Workspace writes require both
``CM_MCP_ALLOW_WRITES=1`` and an explicit ``confirm=True`` argument.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import MODEL, WORKSPACE_PATH
from ..tools.file_ops import file_list, file_read, file_write
from ..tools.rag import codebase_search as search_codebase


logger = logging.getLogger(__name__)
mcp = FastMCP("Mighty Coding Machine (MCM)")


def _writes_enabled() -> bool:
    return os.getenv("CM_MCP_ALLOW_WRITES", "0").strip().lower() in {"1", "true", "yes", "on"}


@mcp.tool()
def workspace_info() -> dict[str, Any]:
    """Return non-sensitive CM workspace and MCP capability information."""
    return {
        "success": True,
        "workspace_root": str(WORKSPACE_PATH),
        "model": MODEL,
        "transport": "stdio",
        "write_enabled": _writes_enabled(),
        "capabilities": [
            "workspace_info",
            "workspace_list_files",
            "workspace_read_file",
            "codebase_search",
            "workspace_write_file",
        ],
    }


@mcp.tool()
def workspace_list_files(relative_path: str = ".") -> dict[str, Any]:
    """List files and directories below the configured workspace root."""
    return file_list(relative_path)


@mcp.tool()
def workspace_read_file(relative_path: str) -> dict[str, Any]:
    """Read a UTF-8 text file below the configured workspace root."""
    return file_read(relative_path)


@mcp.tool()
def codebase_search(query: str, file_types: list[str] | None = None) -> dict[str, Any]:
    """Search the local indexed codebase using CM's hybrid RAG pipeline."""
    return search_codebase(query, file_types=file_types)


@mcp.tool()
def workspace_write_file(relative_path: str, content: str, confirm: bool = False) -> dict[str, Any]:
    """Write a workspace file only after explicit MCP write enablement and confirmation."""
    if not _writes_enabled():
        return {
            "success": False,
            "requires_confirmation": True,
            "error": "MCP workspace writes are disabled. Set CM_MCP_ALLOW_WRITES=1 and retry with confirm=true.",
        }
    if not confirm:
        return {
            "success": False,
            "requires_confirmation": True,
            "error": "Explicit confirmation is required: retry with confirm=true.",
        }
    return file_write(relative_path, content)


def main() -> None:
    """Run the MCP server over stdio without writing protocol data to stdout."""
    logging.basicConfig(level=logging.INFO, stream=__import__("sys").stderr)
    logger.info("Mighty Coding Machine MCP server starting (stdio)")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
