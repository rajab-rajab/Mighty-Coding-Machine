from __future__ import annotations

from app import Api


def test_workspace_copy_creates_unique_file_without_overwriting(monkeypatch, tmp_path):
    monkeypatch.setattr("app.resolve_workspace_path", lambda path: tmp_path / path)
    source = tmp_path / "main.py"
    source.write_text("print('MCM')\n", encoding="utf-8")
    api = Api()

    first_copy = api.copy_workspace_item("main.py")
    second_copy = api.copy_workspace_item("main.py")

    assert first_copy == {"success": True, "path": "main - Copy.py", "is_dir": False}
    assert second_copy == {"success": True, "path": "main - Copy 2.py", "is_dir": False}
    assert (tmp_path / "main - Copy.py").read_text(encoding="utf-8") == "print('MCM')\n"
    assert (tmp_path / "main - Copy 2.py").read_text(encoding="utf-8") == "print('MCM')\n"


def test_workspace_copy_blocks_pasting_folder_into_itself(monkeypatch, tmp_path):
    monkeypatch.setattr("app.resolve_workspace_path", lambda path: tmp_path / path)
    project = tmp_path / "project"
    project.mkdir()

    result = Api().copy_workspace_item("project", "project")

    assert result["success"] is False
    assert "cannot be pasted" in result["error"]
