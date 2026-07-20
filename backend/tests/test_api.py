from __future__ import annotations

from backend.exceptions import PathTraversalError

def test_skills_endpoint_returns_skills(app):
    response = app.test_client().get("/api/skills")

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload["skills"], list)


def test_tools_endpoint_returns_built_in_tool_catalog(app):
    response = app.test_client().get("/api/tools")

    assert response.status_code == 200
    payload = response.get_json()
    tool_ids = {tool["id"] for tool in payload["tools"]}
    assert len(payload["tools"]) == 25
    assert {"file-read", "codebase-search", "run-tests", "git-action", "memory-search"} <= tool_ids


def test_mcp_servers_endpoint_returns_disabled_presets(app):
    response = app.test_client().get("/api/mcp/servers")

    assert response.status_code == 200
    payload = response.get_json()
    assert {server["server_id"] for server in payload["servers"]} >= {
        "fetch",
        "git",
        "github",
        "codex_cli_bridge",
        "openai_remote",
    }
    assert all(server["enabled"] is False for server in payload["servers"])


def test_cm_exception_handler_returns_standard_json(app):
    @app.get("/test-path-error")
    def path_error():
        raise PathTraversalError("Path traversal detected")

    response = app.test_client().get("/test-path-error")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Path traversal detected"}
