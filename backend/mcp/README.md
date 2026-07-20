# Coding Machine MCP Integration

Coding Machine exposes an optional, local MCP server over stdio. It is not
started automatically with the desktop application.

## Start

From the repository's `coding-machine` directory:

```powershell
..\.venv\Scripts\python.exe -m backend.mcp.server
```

Configure an MCP host to launch the same command with `coding-machine` as its
working directory.

## Tools

- `workspace_info`
- `workspace_list_files`
- `workspace_read_file`
- `codebase_search`
- `workspace_write_file`

Reads and RAG search are enabled by default. Writes are disabled by default.
To enable a write, set `CM_MCP_ALLOW_WRITES=1` in the MCP server process and
send `confirm=true`. All paths remain restricted to CM's configured workspace.

The server intentionally does not expose shell execution, database writes,
deployment, Git remotes, or credentials through MCP.

## CM as an MCP client

The desktop app includes an MCP Server Manager under the **MCP** tab. Every
server starts disabled and is launched only after the user saves its
configuration, clicks **Connect**, and approves the launch.

- **Fetch**: read-only web fetch preset (`uvx mcp-server-fetch`).
- **Git**: read-only repository preset (`uvx mcp-server-git --repository <workspace>`).
- **GitHub**: read-only preset (`npx -y @modelcontextprotocol/server-github`).
  Set `GITHUB_PERSONAL_ACCESS_TOKEN` in the process environment; never paste
  secrets into CM's MCP panel.
- **Codex CLI bridge**: runs CM's local MCP server, so Codex CLI can be
  configured to launch the same command shown above. Codex CLI itself is an
  MCP client, not an MCP server.
- **OpenAI-compatible remote MCP**: configure a trusted streamable HTTP MCP
  endpoint. CM does not assume a generic OpenAI MCP URL.

CM discovers tools after connection, enforces per-server timeouts, writes an
audit log to `workspace/logs/mcp.log`, blocks mutating tools for read-only
servers, and requires interactive approval before local server launches or
mutating tool calls. Connected, allowed tools are also injected dynamically
into CM's existing agent function list; disconnected or blocked tools are
never sent to the model.
