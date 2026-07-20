"""OpenAI function tools backed by the synchronous SQLAlchemy manager."""

from __future__ import annotations

from typing import Any

from ..approval import ApprovalLevel, approval_manager, database_approval_level
from ..config import WORKSPACE_PATH
from ..security import validate_sql_query
from .db_manager import database_manager


DB_CONNECT_TOOL = {
    "type": "function",
    "function": {
        "name": "db_connect",
        "description": "Connect to and test a SQLite, PostgreSQL, or MySQL database.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string", "description": "Stable ID for this connection."},
                "db_type": {"type": "string", "enum": ["sqlite", "postgresql", "mysql"]},
                "connection_string": {"type": "string", "description": "Database URL or workspace-relative SQLite path."},
            },
            "required": ["connection_id", "db_type", "connection_string"],
            "additionalProperties": False,
        },
    },
}
DB_CONNECT_SCHEMA = DB_CONNECT_TOOL

DB_LIST_TABLES_TOOL = {
    "type": "function",
    "function": {
        "name": "db_list_tables",
        "description": "List tables for an active database connection.",
        "parameters": {
            "type": "object",
            "properties": {"connection_id": {"type": "string"}},
            "required": ["connection_id"],
            "additionalProperties": False,
        },
    },
}
DB_LIST_TABLES_SCHEMA = DB_LIST_TABLES_TOOL

DB_EXECUTE_QUERY_TOOL = {
    "type": "function",
    "function": {
        "name": "db_execute_query",
        "description": "Execute raw SQL and return columns and JSON-safe rows.",
        "parameters": {
            "type": "object",
            "properties": {
                "connection_id": {"type": "string"},
                "sql_query": {"type": "string"},
            },
            "required": ["connection_id", "sql_query"],
            "additionalProperties": False,
        },
    },
}
DB_EXECUTE_QUERY_SCHEMA = DB_EXECUTE_QUERY_TOOL

# Compatibility alias for callers that imported the Prompt-2 constant.
DB_EXECUTE_TOOL = DB_EXECUTE_QUERY_TOOL
DB_EXECUTE_SCHEMA = DB_EXECUTE_QUERY_TOOL


def db_connect(connection_id: str, db_type: str, connection_string: str) -> dict[str, Any]:
    """Create and test a named synchronous database connection."""
    return database_manager.connect(connection_id, db_type, connection_string)


def db_list_tables(connection_id: str) -> dict[str, Any]:
    """List tables through SQLAlchemy's dialect-specific inspector."""
    return database_manager.list_tables(connection_id)


def db_execute_query(
    connection_id: str,
    sql_query: str,
    emit_event: Any = None,
    cancel_event: Any = None,
) -> dict[str, Any]:
    """Execute a query and return columns, rows, and row count."""
    validation = validate_sql_query(sql_query, WORKSPACE_PATH)
    if validation.get("blocked"):
        return {
            "success": False,
            "connection_id": connection_id,
            "blocked": True,
            "reason": validation["reason"],
            "message": "The database operation was blocked because its file target is outside the workspace.",
        }
    approval_level = database_approval_level(sql_query)
    if approval_level != ApprovalLevel.AUTOMATIC:
        if emit_event is None:
            return {
                "success": False,
                "connection_id": connection_id,
                "requires_confirmation": True,
                "reason": validation.get("reason", "Database writes require user approval."),
                "message": "Ask user for confirmation before running.",
            }
        approval = approval_manager.request(
            category="database",
            action="execute_sql",
            summary="Run a database write operation",
            details=sql_query,
            emit_event=emit_event,
            level=approval_level,
            cancel_event=cancel_event,
        )
        if not approval.get("approved"):
            return {
                "success": False,
                "connection_id": connection_id,
                "requires_approval": True,
                "level": approval_level.value,
                "message": approval.get("message", "Database operation was not approved."),
            }
    if validation.get("requires_confirmation") and emit_event is None:
        return {
            "success": False,
            "connection_id": connection_id,
            "requires_confirmation": True,
            "reason": validation["reason"],
            "message": "Ask user for confirmation before running.",
        }
    return database_manager.execute_query(connection_id, sql_query)


def db_execute(query: str, database: str = "cm.db", emit_event: Any = None, cancel_event: Any = None) -> dict[str, Any]:
    """Prompt-2 compatibility wrapper for workspace-local SQLite calls."""
    connection_id = "__legacy_sqlite__"
    connected = db_connect(connection_id, "sqlite", database)
    if not connected.get("success"):
        return connected
    result = db_execute_query(connection_id, query, emit_event=emit_event, cancel_event=cancel_event)
    if result.get("success"):
        return {"success": True, "rows": result.get("rows", []), "rowcount": result.get("rowcount", -1)}
    return result
