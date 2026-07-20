"""Conditional deployment and release specialist."""

from __future__ import annotations

from .base import AgentDefinition
from ..tools.deployment import REQUEST_DEPLOYMENT_APPROVAL_TOOL
from ..tools.file_ops import FILE_LIST_TOOL, FILE_READ_TOOL
from ..tools.rag import CODEBASE_SEARCH_TOOL


class DeploymentAgent(AgentDefinition):
    def __init__(self) -> None:
        super().__init__(
            name="Deployment Agent",
            system_prompt=(
                "You are the Deployment Agent for Coding Machine. Handle packaging, release, and deployment requests. "
                "Inspect the project and deployment configuration first, present an exact release plan, and request "
                "elevated approval before any deployment action. Do not claim deployment succeeded without evidence."
            ),
            tools=(FILE_READ_TOOL, FILE_LIST_TOOL, CODEBASE_SEARCH_TOOL, REQUEST_DEPLOYMENT_APPROVAL_TOOL),
        )
