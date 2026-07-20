from __future__ import annotations

import os
import sys
from pathlib import Path

import anyio


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _text_content(result) -> str:
    parts = []
    for item in result.content:
        text = getattr(item, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


async def _run_mcp_protocol_checks() -> dict[str, object]:
    backend_path = str(PROJECT_ROOT / "backend")
    sys.path[:] = [entry for entry in sys.path if str(Path(entry or ".").resolve()) != backend_path]
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "backend.mcp.server"],
        cwd=PROJECT_ROOT,
        env={**os.environ, "CM_MCP_ALLOW_WRITES": "0", "PYTHONPATH": str(PROJECT_ROOT)},
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            info = await session.call_tool("workspace_info", {})
            blocked_write = await session.call_tool(
                "workspace_write_file",
                {"relative_path": "mcp-test.txt", "content": "should not be written"},
            )
            blocked_read = await session.call_tool("workspace_read_file", {"relative_path": "../outside.txt"})
            return {
                "tools": {tool.name for tool in tools.tools},
                "info": _text_content(info),
                "blocked_write": _text_content(blocked_write),
                "blocked_read": _text_content(blocked_read),
            }


def test_mcp_stdio_server_exposes_scoped_tools_and_blocks_writes_by_default():
    result = anyio.run(_run_mcp_protocol_checks)

    assert result["tools"] == {
        "workspace_info",
        "workspace_list_files",
        "workspace_read_file",
        "codebase_search",
        "workspace_write_file",
    }
    assert "workspace_root" in str(result["info"])
    assert "disabled" in str(result["blocked_write"])
    assert "outside" in str(result["blocked_read"]).lower() or "traversal" in str(result["blocked_read"]).lower()
    assert not (PROJECT_ROOT / "workspace" / "mcp-test.txt").exists()
