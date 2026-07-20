from __future__ import annotations

from backend.agents.capabilities import CapabilityRouter
from backend.agents.engine import AgentEngine


def test_database_request_recommends_database_specialist_and_skill():
    recommendation = CapabilityRouter().recommend("Create a PostgreSQL schema for customer invoices")

    assert recommendation.agent == "Database Agent"
    assert "database-engineering" in recommendation.skills
    assert {"db-list-tables", "db-execute-query"} <= set(recommendation.tools)


def test_security_request_has_priority_over_other_intent():
    recommendation = CapabilityRouter().recommend("Audit the Flask API for SQL injection and authentication issues")

    assert recommendation.agent == "Security Agent"
    assert {"security-audit", "codebase-rag"} <= set(recommendation.skills)
    assert {"project-inventory", "dependency-manifest", "workspace-search"} <= set(recommendation.tools)


def test_frontend_request_recommends_ui_skill_and_language_skill():
    recommendation = CapabilityRouter().recommend("Update the HTML and CSS for the browser dashboard")

    assert recommendation.agent == "Frontend Agent"
    assert {"frontend-ui", "html-css"} <= set(recommendation.skills)
    assert {"workspace-search", "file-read"} <= set(recommendation.tools)


def test_complex_request_recommends_planning_skill():
    recommendation = CapabilityRouter().recommend("Build a full application with multiple files and tests")

    assert recommendation.agent == "Planner Agent"
    assert "requirements-planning" in recommendation.skills
    assert {"create-plan", "project-inventory"} <= set(recommendation.tools)


def test_engine_applies_recommendation_to_orchestration(mocker):
    captured: dict[str, object] = {}
    events: list[tuple[str, dict[str, object]]] = []

    def fake_orchestration(**kwargs):
        captured.update(kwargs)
        return "Completed"

    mocker.patch("backend.agents.engine.run_orchestration", side_effect=fake_orchestration)
    mocker.patch("backend.agents.engine.agent_performance_store.record_run", return_value={})

    response = AgentEngine(client=object()).run(
        "Audit this workspace for secrets and SQL injection",
        lambda event, payload: events.append((event, payload)),
    )

    assert response == "Completed"
    assert {"security-audit", "codebase-rag"} <= set(captured["active_skills"])
    assert {"project-inventory", "dependency-manifest", "workspace-search"} <= set(captured["active_tools"])
    assert captured["routing_hint"]["agent"] == "Security Agent"
    assert any(event == "capability_recommendation" for event, _ in events)
