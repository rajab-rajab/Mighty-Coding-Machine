"""Shared agent definition used by the lightweight CM agent engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..skills.agent_templates import get_role_playbook
from ..skills.global_template import apply_global_template


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    system_prompt: str
    tools: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        prompt = f"{get_role_playbook(self.name)}\n\n{self.system_prompt}"
        object.__setattr__(self, "system_prompt", apply_global_template(prompt))
