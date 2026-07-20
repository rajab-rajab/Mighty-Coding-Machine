"""SQLite-backed persistent user preferences."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from ..config import WORKSPACE_PATH


DEFAULT_PREFERENCES_PATH = WORKSPACE_PATH / "preferences.db"


class MetadataStore:
    """Store simple key/value preferences in a local SQLite database."""

    def __init__(self, path: str | Path = DEFAULT_PREFERENCES_PATH) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    def update(self, key: str, value: Any) -> dict[str, Any]:
        if not key.strip():
            return {"success": False, "error": "Preference key is required"}
        with self._lock, sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )
        return {"success": True, "key": key, "value": str(value)}

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._lock, sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default

    def all(self) -> dict[str, str]:
        with self._lock, sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT key, value FROM preferences ORDER BY key").fetchall()
        return {key: value for key, value in rows}


metadata_store = MetadataStore()
