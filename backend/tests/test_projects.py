from __future__ import annotations

import json

from backend.project_manager import create_project
from backend.agents.orchestrator import _execute_tool
from backend.tools import file_ops
from backend.tools.file_ops import file_read, file_write, project_scope


def test_projects_are_unique_and_files_are_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.project_manager.WORKSPACE_PATH", tmp_path)
    monkeypatch.setattr(file_ops, "WORKSPACE_PATH", tmp_path)

    projects = [create_project("Create a Greeting App") for _ in range(3)]

    assert [project.name for project in projects] == ["Greeting_App", "Greeting_App_2", "Greeting_App_3"]
    for index, project in enumerate(projects, start=1):
        with project_scope(project.relative_path):
            assert file_write("main.py", f"print({index})")['success'] is True
        assert (tmp_path / project.relative_path / "main.py").read_text(encoding="utf-8") == f"print({index})"
        assert file_read(f"{project.relative_path}/main.py")["content"] == f"print({index})"


def test_scaffold_project_emits_file_change_events():
    events = []
    result = _execute_tool(
        "scaffold_project",
        '{"files": {"main.py": "print(1)"}}',
        lambda event, payload: events.append((event, payload)),
        {
            "scaffold_project": lambda files: {
                "success": True,
                "files": {path: {"success": True, "path": f"Greeting_App/{path}"} for path in files},
            }
        },
    )

    assert result["success"] is True
    assert events == [("workspace_file_changed", {"path": "Greeting_App/main.py"})]


def test_agent_file_write_completes_without_diff_review(tmp_path, monkeypatch):
    monkeypatch.setattr(file_ops, "WORKSPACE_PATH", tmp_path)
    events = []

    result = _execute_tool(
        "file_write",
        json.dumps({"path": "main.py", "content": "print('ready')\n"}),
        lambda event, payload: events.append((event, payload)),
        {},
    )

    assert result["success"] is True
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('ready')\n"
    assert not any(event == "code_diff_review" for event, _ in events)
