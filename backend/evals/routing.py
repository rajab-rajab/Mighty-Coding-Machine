"""Fast, offline routing evaluations that do not call OpenAI."""

from __future__ import annotations

from typing import Any

from ..agents.orchestrator import Orchestrator


ROUTING_CASES: tuple[dict[str, str], ...] = (
    {"id": "code", "prompt": "Add validation to this Python function", "expected": "Code Agent"},
    {"id": "database", "prompt": "Create a database schema and query", "expected": "Database Agent"},
    {"id": "debug", "prompt": "Debug this traceback and failing test", "expected": "Debug Agent"},
    {"id": "frontend", "prompt": "Improve the CSS and browser UI", "expected": "Frontend Agent"},
    {"id": "git", "prompt": "Show Git status and commit these changes", "expected": "Git Agent"},
    {"id": "security", "prompt": "Audit authentication for vulnerabilities", "expected": "Security Agent"},
    {"id": "deployment", "prompt": "Package and deploy this release", "expected": "Deployment Agent"},
    {"id": "complex", "prompt": "Build a full application with multiple files and tests", "expected": "Planner Agent"},
)


def run_routing_regression_suite() -> dict[str, Any]:
    """Evaluate deterministic routing behavior without API credentials."""
    results = []
    for case in ROUTING_CASES:
        routed = Orchestrator._heuristic_route(case["prompt"])
        results.append(
            {
                "id": case["id"],
                "expected": case["expected"],
                "actual": routed["agent"],
                "passed": routed["agent"] == case["expected"],
                "confidence": routed.get("confidence", 0),
                "reason": routed.get("reason", ""),
            }
        )
    passed = sum(1 for result in results if result["passed"])
    return {"success": passed == len(results), "passed": passed, "total": len(results), "results": results}

