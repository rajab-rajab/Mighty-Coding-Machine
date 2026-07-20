from __future__ import annotations

import pytest

from backend.security import validate_path, validate_sql_query
from backend.tools.code_exec import run_code


def test_validate_path_allows_workspace_file(tmp_path):
    resolved = validate_path("folder/file.py", tmp_path)

    assert resolved.endswith("folder\\file.py") or resolved.endswith("folder/file.py")


def test_validate_path_blocks_traversal(tmp_path):
    with pytest.raises(PermissionError, match="Path traversal detected"):
        validate_path("../../etc/passwd", tmp_path)


def test_validate_sql_query_flags_drop():
    result = validate_sql_query("DROP TABLE users")

    assert result == {
        "requires_confirmation": True,
        "reason": "Query modifies schema or deletes data.",
    }


def test_validate_sql_query_allows_select():
    assert validate_sql_query("SELECT * FROM users")["requires_confirmation"] is False


def test_validate_sql_query_flags_delete_without_where():
    assert validate_sql_query("DELETE FROM users")["requires_confirmation"] is True
    assert validate_sql_query("DELETE FROM users WHERE id = 1")["requires_confirmation"] is False


def test_agent_code_blocks_dynamic_system_path_mutation():
    result = run_code(
        "from pathlib import Path; target = Path(chr(67)+':')/'Windows'/'cm-security-probe.tmp'; target.unlink()"
    )

    assert result["success"] is False
    assert "security policy" in result.get("stderr", "").lower()


def test_agent_code_allows_workspace_output(tmp_path, monkeypatch):
    import backend.tools.code_exec as code_exec
    import backend.tools.file_ops as file_ops

    monkeypatch.setattr(code_exec, "WORKSPACE_PATH", tmp_path)
    monkeypatch.setattr(file_ops, "WORKSPACE_PATH", tmp_path)
    result = code_exec.run_code("open('agent-output.txt', 'w', encoding='utf-8').write('safe')")

    assert result["success"] is True
    assert (tmp_path / "agent-output.txt").read_text(encoding="utf-8") == "safe"


def test_agent_node_filesystem_module_is_blocked():
    result = run_code("require('fs').rmSync('anything')", language="node")

    assert result["success"] is False
    assert "security policy" in result["error"].lower()


def test_agent_node_runtime_escape_is_blocked():
    result = run_code("process.binding('fs')", language="node")

    assert result["success"] is False
    assert "security policy" in result["error"].lower()


def test_sql_file_target_outside_workspace_is_blocked(tmp_path):
    result = validate_sql_query("ATTACH DATABASE 'C:/Windows/cm.db' AS system_db", tmp_path)

    assert result["blocked"] is True
    assert result["requires_confirmation"] is False


def test_dynamic_sql_file_target_is_blocked(tmp_path):
    result = validate_sql_query("ATTACH DATABASE (printf('C:/Windows/cm.db')) AS system_db", tmp_path)

    assert result["blocked"] is True


def test_test_agent_blocks_external_file_deletion(tmp_path, monkeypatch):
    import backend.tools.file_ops as file_ops
    import backend.tools.test_runner as test_runner

    monkeypatch.setattr(file_ops, "WORKSPACE_PATH", tmp_path)
    monkeypatch.setattr(test_runner, "WORKSPACE_PATH", tmp_path)
    (tmp_path / "test_delete.py").write_text(
        "from pathlib import Path\n"
        "def test_delete():\n"
        "    Path(chr(67)+':') / 'Windows' / 'cm-security-probe.tmp'\n"
        "    (Path(chr(67)+':') / 'Windows' / 'cm-security-probe.tmp').unlink()\n",
        encoding="utf-8",
    )

    result = test_runner.run_tests(["test_delete.py"], timeout=30)

    assert result["success"] is False
    assert "security policy" in result["stdout"].lower()
