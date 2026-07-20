from __future__ import annotations

import subprocess

from backend.tools.source_control import GitManager


def test_git_status_stage_and_commit(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "cm@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Coding Machine"], check=True)
    (tmp_path / "main.py").write_text('print("hello")\n', encoding="utf-8")

    manager = GitManager(tmp_path)
    status = manager.status()
    assert status["success"] is True
    assert status["is_repo"] is True
    assert status["changes"][0]["path"] == "main.py"
    assert status["changes"][0]["untracked"] is True

    assert manager.stage("main.py")["success"] is True
    staged = manager.status()
    assert staged["changes"][0]["staged"] is True
    assert manager.commit("Add main script")["success"] is True
    assert manager.status()["changes"] == []


def test_git_rejects_path_outside_workspace(tmp_path):
    manager = GitManager(tmp_path)
    result = manager.stage("../outside.txt")
    assert result["success"] is False
    assert "outside" in result["error"].lower() or "traversal" in result["error"].lower()


def test_git_actions_use_nested_project_scope(tmp_path):
    project = tmp_path / "nested-project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "cm@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "Mighty Coding Machine"], check=True)
    (project / "main.py").write_text('print("nested")\n', encoding="utf-8")

    manager = GitManager(tmp_path)
    assert manager.status("nested-project")["is_repo"] is True
    assert manager.diff("nested-project/main.py", project_path="nested-project")["success"] is True
    assert manager.stage("nested-project/main.py", "nested-project")["success"] is True
    assert manager.commit("Add nested project", "nested-project")["success"] is True
    assert manager.status("nested-project")["changes"] == []


def test_git_init_branches_history_and_untracked_diff(tmp_path):
    manager = GitManager(tmp_path)

    initialized = manager.init()
    assert initialized["success"] is True
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
    assert manager.stage("main.py")["success"] is True
    assert manager.commit("Initial commit")["success"] is True

    branch_info = manager.branches()
    assert branch_info["success"] is True
    assert branch_info["current"] in branch_info["branches"]
    assert manager.history()["history"][0]["subject"] == "Initial commit"

    untracked = tmp_path / "new.py"
    untracked.write_text("print('new')\n", encoding="utf-8")
    diff = manager.diff("new.py")
    assert diff["success"] is True
    assert any(line["type"] == "added" for line in diff["diff_lines"])

    feature = "feature-test"
    subprocess.run(["git", "-C", str(tmp_path), "switch", "-c", feature], check=True)
    assert manager.switch_branch(branch_info["current"])["success"] is True
    assert manager.branches()["current"] == branch_info["current"]


def test_git_remote_metadata_and_ref_validation(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    manager = GitManager(tmp_path)
    subprocess.run(["git", "-C", str(tmp_path), "remote", "add", "origin", "https://example.invalid/cm.git"], check=True)

    remotes = manager.remotes()
    assert remotes["success"] is True
    assert remotes["remotes"][0]["name"] == "origin"
    assert manager.push("-bad")["success"] is False
