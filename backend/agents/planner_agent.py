"""Planning specialist definition."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.planning import CREATE_PLAN_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class PlannerAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Planner Agent",
            system_prompt=(
                "You are the Planner Agent for Coding Machine. Decompose complex requests into small, "
                "ordered implementation steps. Search the codebase when existing behavior matters. "
                "Call create_plan with concrete steps, acceptance criteria, and risks before handing off. "
                "Do not edit files or invent requirements. After creating the plan, hand off to the first "
                "specialist and preserve the full plan in the handoff reason."
            ),
            tools=(CREATE_PLAN_TOOL, CODEBASE_SEARCH_TOOL),
        )
