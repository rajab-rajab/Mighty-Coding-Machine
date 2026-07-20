"""Bounded execution policies for each Coding Machine agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class AgentPolicy:
    token_budget: int
    timeout_seconds: int
    retry_limit: int = 2


AGENT_POLICIES: dict[str, AgentPolicy] = {
    "Orchestrator": AgentPolicy(token_budget=2_000, timeout_seconds=60),
    "Planner Agent": AgentPolicy(token_budget=4_000, timeout_seconds=120),
    "Code Agent": AgentPolicy(token_budget=8_000, timeout_seconds=180),
    "Database Agent": AgentPolicy(token_budget=4_000, timeout_seconds=120),
    "Debug Agent": AgentPolicy(token_budget=5_000, timeout_seconds=150),
    "Review Agent": AgentPolicy(token_budget=5_000, timeout_seconds=150),
    "Project Agent": AgentPolicy(token_budget=6_000, timeout_seconds=150),
    "Test Agent": AgentPolicy(token_budget=5_000, timeout_seconds=180),
    "Deployment Agent": AgentPolicy(token_budget=4_000, timeout_seconds=180),
    "Git Agent": AgentPolicy(token_budget=3_000, timeout_seconds=90),
    "Frontend Agent": AgentPolicy(token_budget=6_000, timeout_seconds=150),
    "Security Agent": AgentPolicy(token_budget=5_000, timeout_seconds=180),
}


DEFAULT_AGENT_POLICY = AgentPolicy(token_budget=4_000, timeout_seconds=120)


def get_agent_policy(agent_name: str) -> AgentPolicy:
    return AGENT_POLICIES.get(str(agent_name).strip(), DEFAULT_AGENT_POLICY)


def policy_snapshot() -> dict[str, dict[str, Any]]:
    return {agent_name: asdict(policy) for agent_name, policy in AGENT_POLICIES.items()}
