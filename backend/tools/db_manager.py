"""Synchronous SQLAlchemy connection manager for threaded CM operations."""

from __future__ import annotations

import datetime as dt
import decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, make_url

from .file_ops import resolve_workspace_path


class DatabaseManager:
    """Own active SQLAlchemy engines keyed by client-visible connection IDs."""

    def __init__(self) -> None:
        self.connections: dict[str, Engine] = {}

    def create_engine(self, db_type: str, connection_string: str) -> Engine:
        """Create a synchronous engine for SQLite, PostgreSQL, or MySQL."""
        normalized_type = db_type.strip().lower()
        url = self._normalize_url(normalized_type, connection_string)
        engine_options: dict[str, Any] = {
            "pool_pre_ping": True,
            "pool_timeout": 5,
        }

        if normalized_type == "sqlite":
            engine_options["connect_args"] = {"timeout": 5, "check_same_thread": False}
            if url == "sqlite:///:memory:":
                from sqlalchemy.pool import StaticPool

                engine_options["poolclass"] = StaticPool
                engine_options.pop("pool_timeout", None)
        else:
            engine_options.update({"pool_size": 5, "max_overflow": 5})

        return sqlalchemy_create_engine(url, **engine_options)

    def connect(self, connection_id: str, db_type: str, connection_string: str) -> dict[str, Any]:
        """Create, test, and store an engine under a connection ID."""
        connection_id = connection_id.strip()
        if not connection_id:
            return {"success": False, "error": "connection_id is required"}

        old_engine = self.connections.pop(connection_id, None)
        if old_engine is not None:
            old_engine.dispose()

        try:
            engine = self.create_engine(db_type, connection_string)
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            self.connections[connection_id] = engine
            return {"success": True, "connection_id": connection_id, "db_type": db_type.lower()}
        except Exception as exc:
            if "engine" in locals():
                engine.dispose()
            return {"success": False, "error": str(exc), "connection_id": connection_id}

    def disconnect(self, connection_id: str) -> dict[str, Any]:
        engine = self.connections.pop(connection_id, None)
        if engine is None:
            return {"success": False, "error": f"Unknown connection: {connection_id}"}
        engine.dispose()
        return {"success": True, "connection_id": connection_id}

    def get_engine(self, connection_id: str) -> Engine:
        try:
            return self.connections[connection_id]
        except KeyError as exc:
            raise ValueError(f"Unknown connection: {connection_id}") from exc

    def list_tables(self, connection_id: str) -> dict[str, Any]:
        """List tables using SQLAlchemy's dialect-aware inspector."""
        try:
            table_names = inspect(self.get_engine(connection_id)).get_table_names()
            return {"success": True, "connection_id": connection_id, "tables": table_names}
        except Exception as exc:
            return {"success": False, "connection_id": connection_id, "error": str(exc)}

    def execute_query(self, connection_id: str, sql_query: str) -> dict[str, Any]:
        """Execute raw SQL synchronously and return JSON-safe columns and rows."""
        if not sql_query.strip():
            return {"success": False, "connection_id": connection_id, "error": "sql_query is required"}

        try:
            with self.get_engine(connection_id).begin() as connection:
                result = connection.execute(text(sql_query))
                columns = list(result.keys()) if result.returns_rows else []
                rows = [
                    {column: self._json_safe(row[index]) for index, column in enumerate(columns)}
                    for row in result.fetchall()
                ] if result.returns_rows else []
                return {
                    "success": True,
                    "connection_id": connection_id,
                    "columns": columns,
                    "rows": rows,
                    "rowcount": result.rowcount,
                }
        except Exception as exc:
            return {"success": False, "connection_id": connection_id, "error": str(exc)}

    @staticmethod
    def _normalize_url(db_type: str, connection_string: str) -> str:
        raw = connection_string.strip()
        if not raw:
            raise ValueError("connection_string is required")

        if db_type == "sqlite":
            if raw in {":memory:", "sqlite:///:memory:"}:
                return "sqlite:///:memory:"
            if raw.startswith("sqlite+aiosqlite://"):
                raw = raw.replace("sqlite+aiosqlite://", "sqlite://", 1)
            if raw.startswith("sqlite://"):
                database = make_url(raw).database
                if database in {None, ":memory:"}:
                    return "sqlite:///:memory:"
                database_path = resolve_workspace_path(database)
                return f"sqlite:///{Path(database_path).as_posix()}"
            database_path = resolve_workspace_path(raw)
            return f"sqlite:///{Path(database_path).as_posix()}"

        if db_type == "postgresql":
            if raw.startswith("postgres://"):
                return "postgresql+psycopg2://" + raw.removeprefix("postgres://")
            if raw.startswith("postgresql+asyncpg://"):
                return raw.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)
            if raw.startswith("postgresql://"):
                return raw.replace("postgresql://", "postgresql+psycopg2://", 1)
            if raw.startswith("postgresql+psycopg2://"):
                return raw
            raise ValueError("PostgreSQL connection strings must use a postgresql:// URL")

        if db_type == "mysql":
            if raw.startswith("mysql+aiomysql://"):
                return raw.replace("mysql+aiomysql://", "mysql+pymysql://", 1)
            if raw.startswith("mysql://"):
                return raw.replace("mysql://", "mysql+pymysql://", 1)
            if raw.startswith("mysql+pymysql://"):
                return raw
            raise ValueError("MySQL connection strings must use a mysql:// URL")

        raise ValueError(f"Unsupported database type: {db_type}")

    @staticmethod
    def _json_safe(value: Any) -> Any:
        if isinstance(value, (dt.datetime, dt.date, dt.time)):
            return value.isoformat()
        if isinstance(value, decimal.Decimal):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        return value


database_manager = DatabaseManager()
