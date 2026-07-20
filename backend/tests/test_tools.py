from __future__ import annotations

from backend.tools.code_exec import run_code
from backend.tools.database import db_execute_query
from backend.tools.file_ops import file_read, file_write


def test_file_write_and_read(mock_workspace):
    written = file_write("folder/example.txt", "hello CM")
    read = file_read("folder/example.txt")

    assert written["success"] is True
    assert read == {
        "success": True,
        "path": "folder/example.txt",
        "content": "hello CM",
    }


def test_run_code_captures_stdout():
    result = run_code("print('hello from test')")

    assert result["success"] is True
    assert result["stdout"].strip() == "hello from test"


def test_destructive_query_requires_confirmation():
    result = db_execute_query("not-connected", "DROP TABLE users")

    assert result["requires_confirmation"] is True
    assert result["message"] == "Ask user for confirmation before running."

