"""Persistent agent performance aggregates and execution history."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..config import WORKSPACE_PATH


DEFAULT_AGENT_METRICS_PATH = WORKSPACE_PATH / "agent_metrics.db"


class AgentPerformanceStore:
    """Store per-agent run outcomes and aggregate success metrics in SQLite."""

    def __init__(self, path: str | Path = DEFAULT_AGENT_METRICS_PATH) -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_performance (
                    agent_name TEXT PRIMARY KEY,
                    runs INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    failures INTEGER NOT NULL DEFAULT 0,
                    cancelled INTEGER NOT NULL DEFAULT 0,
                    total_execution_seconds REAL NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0,
                    last_status TEXT NOT NULL,
                    last_run_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    run_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model TEXT NOT NULL,
                    execution_time_seconds REAL NOT NULL,
                    total_tokens INTEGER NOT NULL,
                    handoff_count INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    recorded_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_recorded_at ON agent_runs(recorded_at)")

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _agents(metrics: dict[str, Any]) -> list[str]:
        agents = metrics.get("agents", [])
        names = list(dict.fromkeys(str(agent).strip() for agent in agents if str(agent).strip()))
        if names:
            return names
        handoffs = metrics.get("handoff_trace", [])
        for handoff in handoffs:
            if isinstance(handoff, dict):
                for key in ("from", "to"):
                    name = str(handoff.get(key, "")).strip()
                    if name and name not in names:
                        names.append(name)
        return names or ["Orchestrator"]

    @classmethod
    def _agent_entries(cls, metrics: dict[str, Any]) -> list[dict[str, Any]]:
        turns = metrics.get("agent_turns")
        if isinstance(turns, list) and turns:
            return [turn for turn in turns if isinstance(turn, dict) and str(turn.get("agent_name", "")).strip()]
        return [
            {
                "agent_name": agent_name,
                "execution_time_seconds": metrics.get("execution_time_seconds", 0),
                "total_tokens": metrics.get("total_tokens", 0),
            }
            for agent_name in cls._agents(metrics)
        ]

    def record_run(
        self,
        metrics: dict[str, Any],
        request_id: str = "",
        status: str = "success",
        error: str = "",
    ) -> dict[str, Any]:
        """Record one request for every participating agent and return a snapshot."""
        normalized_status = status if status in {"success", "error", "cancelled"} else "error"
        recorded_at = self._now()
        agent_entries = self._agent_entries(metrics)
        task_state = metrics.get("task_state") if isinstance(metrics.get("task_state"), dict) else {}
        task_id = str(task_state.get("task_id", ""))
        model = str(metrics.get("model", ""))
        execution_time = float(metrics.get("execution_time_seconds", 0) or 0)
        total_tokens = int(metrics.get("total_tokens", 0) or 0)
        handoff_count = len(metrics.get("handoff_trace", []) or [])

        with self._lock, sqlite3.connect(self.path) as connection:
            for entry in agent_entries:
                agent_name = str(entry["agent_name"]).strip()
                turn_execution_time = float(entry.get("execution_time_seconds", execution_time) or 0)
                turn_total_tokens = int(entry.get("total_tokens", total_tokens) or 0)
                connection.execute(
                    """
                    INSERT INTO agent_runs
                    (run_id, request_id, task_id, agent_name, status, model,
                     execution_time_seconds, total_tokens, handoff_count, error, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        str(request_id),
                        task_id,
                        agent_name,
                        normalized_status,
                        model,
                        turn_execution_time,
                        turn_total_tokens,
                        handoff_count,
                        str(error),
                        recorded_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO agent_performance
                    (agent_name, runs, successes, failures, cancelled,
                     total_execution_seconds, total_tokens, last_status, last_run_at)
                    VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(agent_name) DO UPDATE SET
                        runs = runs + 1,
                        successes = successes + excluded.successes,
                        failures = failures + excluded.failures,
                        cancelled = cancelled + excluded.cancelled,
                        total_execution_seconds = total_execution_seconds + excluded.total_execution_seconds,
                        total_tokens = total_tokens + excluded.total_tokens,
                        last_status = excluded.last_status,
                        last_run_at = excluded.last_run_at
                    """,
                    (
                        agent_name,
                        int(normalized_status == "success"),
                        int(normalized_status == "error"),
                        int(normalized_status == "cancelled"),
                        turn_execution_time,
                        turn_total_tokens,
                        normalized_status,
                        recorded_at,
                    ),
                )
        return self.snapshot()

    def summary(self) -> list[dict[str, Any]]:
        with self._lock, sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT agent_name, runs, successes, failures, cancelled,
                       total_execution_seconds, total_tokens, last_status, last_run_at
                FROM agent_performance
                ORDER BY agent_name
                """
            ).fetchall()
        return [
            {
                "agent_name": row[0],
                "runs": row[1],
                "successes": row[2],
                "failures": row[3],
                "cancelled": row[4],
                "success_rate": round((row[2] / row[1]) * 100, 1) if row[1] else 0.0,
                "average_execution_time_seconds": round(row[5] / row[1], 3) if row[1] else 0.0,
                "total_tokens": row[6],
                "last_status": row[7],
                "last_run_at": row[8],
            }
            for row in rows
        ]

    def history(self, limit: int = 25) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        with self._lock, sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                """
                SELECT request_id, task_id, agent_name, status, model,
                       execution_time_seconds, total_tokens, handoff_count, error, recorded_at
                FROM agent_runs
                ORDER BY recorded_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            {
                "request_id": row[0],
                "task_id": row[1],
                "agent_name": row[2],
                "status": row[3],
                "model": row[4],
                "execution_time_seconds": row[5],
                "total_tokens": row[6],
                "handoff_count": row[7],
                "error": row[8],
                "recorded_at": row[9],
            }
            for row in rows
        ]

    def snapshot(self, limit: int = 25) -> dict[str, Any]:
        return {"success": True, "agents": self.summary(), "history": self.history(limit)}


agent_performance_store = AgentPerformanceStore()
