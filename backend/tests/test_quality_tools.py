from __future__ import annotations

import backend.tools.quality as quality
from backend.skills.registry import skill_registry


def test_quality_inventory_search_and_manifest_are_workspace_scoped(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / "Greeting_App"
    project.mkdir(parents=True)
    (project / "main.py").write_text("name = input('Name: ')\nprint(name)\n", encoding="utf-8")
    (project / "requirements.txt").write_text("flask==3.1.0\n", encoding="utf-8")
    monkeypatch.setattr(quality, "WORKSPACE_PATH", workspace)

    inventory = quality.project_inventory("Greeting_App")
    assert inventory["success"] is True
    assert inventory["file_count"] == 2
    assert "Greeting_App/requirements.txt" in inventory["manifests"]

    search = quality.workspace_search("input", "Greeting_App", file_types=["py"])
    assert search["success"] is True
    assert search["results"][0]["path"] == "Greeting_App/main.py"
    assert quality.workspace_search("input", "../")["success"] is False

    manifest = quality.dependency_manifest("Greeting_App")
    assert manifest["success"] is True
    assert manifest["manifests"][0]["path"] == "Greeting_App/requirements.txt"


def test_python_syntax_check_does_not_execute_file(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    valid = workspace / "valid.py"
    invalid = workspace / "invalid.py"
    valid.write_text("value = 1\n", encoding="utf-8")
    invalid.write_text("def broken(:\n", encoding="utf-8")
    monkeypatch.setattr(quality, "WORKSPACE_PATH", workspace)

    assert quality.python_syntax_check("valid.py")["valid"] is True
    result = quality.python_syntax_check("invalid.py")
    assert result["success"] is True
    assert result["valid"] is False


def test_expanded_skill_catalog_injects_only_selected_tools():
    definitions = {skill.id: skill for skill in skill_registry.list()}
    expected = {
        "python",
        "javascript",
        "sqlite",
        "database-engineering",
        "backend-api",
        "frontend-ui",
        "testing-quality",
        "debugging",
        "security-audit",
        "git-workflow",
        "windows-packaging",
        "documentation",
        "requirements-planning",
        "performance-diagnostics",
        "codebase-rag",
        "typescript",
        "html-css",
        "java",
        "csharp",
        "c-cpp",
        "go",
        "rust",
        "php",
        "ruby",
        "kotlin",
        "swift",
    }
    assert expected <= definitions.keys()

    prompt, schemas, functions = skill_registry.get_active_config(["testing-quality"])
    names = {schema["function"]["name"] for schema in schemas}
    assert "Testing and Quality" in prompt
    assert {"project_inventory", "python_syntax_check", "run_tests"} <= names
    assert {"project_inventory", "python_syntax_check", "run_tests"} <= functions.keys()

    prompt, schemas, functions = skill_registry.get_active_config(["rust"])
    names = {schema["function"]["name"] for schema in schemas}
    assert "Rust skill is active" in prompt
    assert {"file_read", "file_write", "file_list", "workspace_search"} <= names
    assert {"file_read", "file_write", "file_list", "workspace_search"} <= functions.keys()
