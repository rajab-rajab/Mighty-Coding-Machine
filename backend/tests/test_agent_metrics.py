from backend.memory.agent_metrics import AgentPerformanceStore


def test_agent_performance_store_persists_aggregate_success_history(tmp_path):
    store = AgentPerformanceStore(tmp_path / "agent_metrics.db")

    first = store.record_run(
        {
            "model": "test-model",
            "agents": ["Planner Agent", "Code Agent"],
            "total_tokens": 120,
            "execution_time_seconds": 1.5,
            "handoff_trace": [{"from": "Planner Agent", "to": "Code Agent"}],
            "task_state": {"task_id": "task-1"},
        },
        request_id="request-1",
        status="success",
    )
    assert first["success"] is True
    assert first["agents"][0]["success_rate"] == 100.0

    store.record_run(
        {
            "model": "test-model",
            "agents": ["Code Agent"],
            "total_tokens": 40,
            "execution_time_seconds": 0.5,
            "task_state": {"task_id": "task-2"},
        },
        request_id="request-2",
        status="error",
        error="tool failed",
    )

    code_summary = next(item for item in store.summary() if item["agent_name"] == "Code Agent")
    assert code_summary["runs"] == 2
    assert code_summary["successes"] == 1
    assert code_summary["failures"] == 1
    assert code_summary["success_rate"] == 50.0
    assert code_summary["total_tokens"] == 160

    history = store.history()
    assert len(history) == 3
    assert history[0]["request_id"] == "request-2"
    assert history[0]["status"] == "error"
    assert history[0]["error"] == "tool failed"


def test_agent_performance_store_tracks_cancelled_runs_and_fallback_agent(tmp_path):
    store = AgentPerformanceStore(tmp_path / "agent_metrics.db")
    store.record_run(
        {"model": "test-model", "total_tokens": 0, "execution_time_seconds": 0.1},
        request_id="request-cancelled",
        status="cancelled",
    )

    summary = store.summary()
    assert summary == [
        {
            "agent_name": "Orchestrator",
            "runs": 1,
            "successes": 0,
            "failures": 0,
            "cancelled": 1,
            "success_rate": 0.0,
            "average_execution_time_seconds": 0.1,
            "total_tokens": 0,
            "last_status": "cancelled",
            "last_run_at": summary[0]["last_run_at"],
        }
    ]


def test_agent_performance_store_uses_turn_level_duration_and_tokens(tmp_path):
    store = AgentPerformanceStore(tmp_path / "agent_metrics.db")
    store.record_run(
        {
            "model": "test-model",
            "agent_turns": [
                {"agent_name": "Planner Agent", "execution_time_seconds": 0.2, "total_tokens": 10},
                {"agent_name": "Code Agent", "execution_time_seconds": 0.8, "total_tokens": 90},
            ],
        },
        request_id="request-turns",
        status="success",
    )

    summary = {item["agent_name"]: item for item in store.summary()}
    assert summary["Planner Agent"]["average_execution_time_seconds"] == 0.2
    assert summary["Planner Agent"]["total_tokens"] == 10
    assert summary["Code Agent"]["average_execution_time_seconds"] == 0.8
    assert summary["Code Agent"]["total_tokens"] == 90


def test_agent_engine_persists_completed_request_metrics(tmp_path, monkeypatch):
    import backend.agents.engine as engine_module

    store = AgentPerformanceStore(tmp_path / "agent_metrics.db")
    monkeypatch.setattr(engine_module, "agent_performance_store", store)
    events = []
    engine = engine_module.AgentEngine(client=object())
    engine.client = None

    response = engine.run("Create a small Python script", lambda event, payload: events.append((event, payload)), request_id="request-engine")

    assert response
    metrics = next(payload for event, payload in events if event == "agent_metrics")
    assert metrics["status"] == "success"
    assert metrics["performance"]["success"] is True
    assert {item["agent_name"] for item in store.summary()} == {"Orchestrator", "Code Agent"}
