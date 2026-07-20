"""Structured planning tool used by the Planner Agent."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any


CREATE_PLAN_TOOL = {
    "type": "function",
    "function": {
        "name": "create_plan",
        "description": "Create a structured implementation plan with acceptance criteria before work begins.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "steps": {"type": "array", "items": {"type": "string"}},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title", "steps", "acceptance_criteria"],
            "additionalProperties": False,
        },
    },
}


def create_plan(
    title: str,
    steps: Iterable[str],
    acceptance_criteria: Iterable[str],
    risks: Iterable[str] | None = None,
    emit_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Emit and return a normalized implementation plan."""
    plan = {
        "title": str(title).strip(),
        "steps": [str(step).strip() for step in steps if str(step).strip()],
        "acceptance_criteria": [
            str(criteria).strip()
            for criteria in acceptance_criteria
            if str(criteria).strip()
        ],
        "risks": [str(risk).strip() for risk in risks or [] if str(risk).strip()],
    }
    if not plan["title"] or not plan["steps"] or not plan["acceptance_criteria"]:
        return {"success": False, "error": "A plan title, steps, and acceptance criteria are required."}
    if emit_event is not None:
        emit_event("agent_plan", plan)
    return {"success": True, "plan": plan}
