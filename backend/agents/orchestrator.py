"""Multi-agent routing and continuous handoff orchestration."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from ..config import MODEL
from .policy import get_agent_policy, policy_snapshot
from ..skills.agent_templates import get_role_playbook
from ..skills.global_template import apply_global_template
from .prompt_cache import build_prompt_cache_key, prompt_cache_arguments
from .structured_output import StructuredOutputError, parse_tool_arguments


ORCHESTRATOR_ROLE_PROMPT = (
    "You are the Coding Machine Orchestrator. Analyze the user's request, determine the next specialist, "
    "and call handoff. You may hand work between specialists when the task has multiple phases. "
    "Use Planner Agent first for complex or multi-step requests. Use Security Agent only for security-sensitive or "
    "release-bound work, Deployment Agent only for packaging or deployment, Git Agent only for explicit source-control "
    "actions, and Frontend Agent only when UI files are involved. "
    "Use Code Agent for implementation, Database Agent for SQL and schemas, Debug Agent for failures, "
    "Review Agent for critique, Project Agent for scaffolding, and Test Agent for creating and running tests. "
    "Do not solve implementation work yourself. "
    "Preserve every explicit user requirement verbatim across handoffs; never substitute a generic template "
    "for the requested output."
)
ORCHESTRATOR_PROMPT = apply_global_template(
    f"{get_role_playbook('Orchestrator')}\n\n{ORCHESTRATOR_ROLE_PROMPT}"
)


@dataclass
class TaskState:
    """Durable structured state shared by every specialist handoff."""

    task_id: str
    user_request: str
    active_skills: list[str] = field(default_factory=list)
    active_tools: list[str] = field(default_factory=list)
    project_path: str = ""
    objective: str = ""
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)
    current_step: str = ""
    completed_work: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    handoff_history: list[dict[str, Any]] = field(default_factory=list)
    tool_history: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_request(
        cls,
        user_request: str,
        context: Any,
        active_skills: list[str],
        active_tools: list[str] | None = None,
    ) -> "TaskState":
        project_path = ""
        context_items = context if isinstance(context, list) else [context]
        for item in context_items:
            content = item.get("content", "") if isinstance(item, dict) else str(item or "")
            marker = "Active project:"
            if marker in content:
                project_text = content.split(marker, 1)[1]
                project_path = project_text.split(". Write all generated files", 1)[0].strip()
                if project_path == project_text.strip():
                    project_path = project_text.split(".", 1)[0].strip()
                break
        return cls(
            task_id=f"task-{uuid4().hex}",
            user_request=str(user_request),
            active_skills=list(dict.fromkeys(str(skill) for skill in active_skills)),
            active_tools=list(dict.fromkeys(str(tool) for tool in (active_tools or []))),
            project_path=project_path,
            objective=str(user_request).strip(),
        )

    @staticmethod
    def _extend_unique(target: list[str], values: Any) -> None:
        if not isinstance(values, (list, tuple, set)):
            return
        for value in values:
            clean = str(value).strip()
            if clean and clean not in target:
                target.append(clean)

    def apply_update(self, update: dict[str, Any] | None) -> None:
        if not isinstance(update, dict):
            return
        for field_name in ("constraints", "acceptance_criteria", "assumptions", "decisions", "completed_work", "next_actions", "risks"):
            self._extend_unique(getattr(self, field_name), update.get(field_name))
        for field_name in ("objective", "current_step"):
            value = update.get(field_name)
            if isinstance(value, str) and value.strip():
                setattr(self, field_name, value.strip())
        project_path = update.get("project_path")
        if isinstance(project_path, str) and project_path.strip():
            self.project_path = project_path.strip()
        if isinstance(update.get("plan"), dict):
            self.apply_plan(update["plan"])
        artifacts = update.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict) and artifact not in self.artifacts:
                    self.artifacts.append(dict(artifact))

    def apply_plan(self, plan: Any) -> None:
        if not isinstance(plan, dict):
            return
        self.plan = dict(plan)
        self._extend_unique(self.acceptance_criteria, plan.get("acceptance_criteria"))
        steps = plan.get("steps")
        if isinstance(steps, list):
            self.next_actions = [str(step).strip() for step in steps if str(step).strip()]
            if self.next_actions and not self.current_step:
                self.current_step = self.next_actions[0]
        self._extend_unique(self.risks, plan.get("risks"))

    def record_handoff(
        self,
        from_agent: str,
        to_agent: str,
        reason: str,
        state_update: dict[str, Any] | None = None,
        confidence: float | None = None,
    ) -> None:
        self.apply_update(state_update)
        self.handoff_history.append(
            {
                "from": from_agent,
                "to": to_agent,
                "reason": str(reason).strip(),
                "confidence": _normalize_confidence(confidence),
                "current_step": self.current_step,
            }
        )

    def record_tool(self, name: str, result: Any) -> None:
        entry = {"name": name, "success": bool(result.get("success")) if isinstance(result, dict) else False}
        if isinstance(result, dict):
            if result.get("error"):
                entry["error"] = str(result["error"])
            if result.get("path"):
                artifact = {"path": str(result["path"]), "source": name}
                if artifact not in self.artifacts:
                    self.artifacts.append(artifact)
            if isinstance(result.get("plan"), dict):
                self.apply_plan(result["plan"])
        self.tool_history.append(entry)
        self.tool_history = self.tool_history[-20:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_request": self.user_request,
            "active_skills": list(self.active_skills),
            "active_tools": list(self.active_tools),
            "project_path": self.project_path,
            "objective": self.objective,
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "assumptions": list(self.assumptions),
            "decisions": list(self.decisions),
            "plan": dict(self.plan),
            "current_step": self.current_step,
            "completed_work": list(self.completed_work),
            "next_actions": list(self.next_actions),
            "risks": list(self.risks),
            "artifacts": list(self.artifacts),
            "handoff_history": list(self.handoff_history),
            "tool_history": list(self.tool_history),
        }

    def prompt_context(self) -> str:
        return "STRUCTURED TASK STATE (AUTHORITATIVE; PRESERVE ACROSS HANDOFFS)\n" + json.dumps(self.snapshot(), indent=2)


HANDOFF_TOOL = {
    "type": "function",
    "function": {
        "name": "handoff",
        "description": "Hand the request to the specialist best suited to continue the work.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                "enum": [
                    "Planner Agent",
                    "Code Agent",
                    "Database Agent",
                    "Debug Agent",
                    "Review Agent",
                    "Project Agent",
                    "Test Agent",
                    "Deployment Agent",
                    "Git Agent",
                    "Frontend Agent",
                    "Security Agent",
                ],
                },
                "reason": {"type": "string"},
                "confidence": {
                    "type": "number",
                    "description": "Confidence that this specialist is the best next agent, from 0.0 to 1.0.",
                    "minimum": 0,
                    "maximum": 1,
                },
                "state_update": {
                    "type": "object",
                    "description": "Structured progress to preserve for the next specialist.",
                    "properties": {
                        "objective": {"type": "string"},
                        "project_path": {"type": "string"},
                        "current_step": {"type": "string"},
                        "constraints": {"type": "array", "items": {"type": "string"}},
                        "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "decisions": {"type": "array", "items": {"type": "string"}},
                        "completed_work": {"type": "array", "items": {"type": "string"}},
                        "next_actions": {"type": "array", "items": {"type": "string"}},
                        "risks": {"type": "array", "items": {"type": "string"}},
                        "plan": {"type": "object"},
                        "artifacts": {"type": "array", "items": {"type": "object"}},
                    },
                    "additionalProperties": False,
                },
            },
            "required": ["agent", "reason"],
            "additionalProperties": False,
        },
    },
}
HANDOFF_SCHEMA = HANDOFF_TOOL


@dataclass(frozen=True)
class AgentConfig:
    """Runtime prompt, schemas, and callable functions for one agent turn."""

    name: str
    system_prompt: str
    tools: tuple[dict[str, Any], ...]
    tool_functions: dict[str, Callable[..., Any]]


class Orchestrator:
    """Route requests and provide the orchestrator system configuration."""

    name = "Orchestrator"
    system_prompt = ORCHESTRATOR_PROMPT
    tools: tuple[dict[str, Any], ...] = ()
    routing_tools = (HANDOFF_TOOL,)

    def route(self, message: str, client: Any = None, model: str = MODEL) -> dict[str, Any]:
        """Return a specialist handoff from OpenAI or a local fallback."""
        if client is not None:
            try:
                cache_key = build_prompt_cache_key(
                    self.system_prompt,
                    list(self.routing_tools),
                    model=model,
                    scope="orchestrator-route",
                )
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": message},
                    ],
                    tools=list(self.routing_tools),
                    tool_choice={"type": "function", "function": {"name": "handoff"}},
                    stream=False,
                    **prompt_cache_arguments(cache_key),
                )
                tool_calls = getattr(response.choices[0].message, "tool_calls", None) or []
                if tool_calls:
                    arguments = json.loads(tool_calls[0].function.arguments)
                    agent = _normalize_agent(arguments.get("agent", "Code Agent"))
                    if agent != "Orchestrator":
                        return {
                            "agent": agent,
                            "reason": arguments.get("reason", ""),
                            "confidence": _normalize_confidence(arguments.get("confidence")),
                        }
            except (AttributeError, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass

        return self._heuristic_route(message)

    @staticmethod
    def _valid_agents() -> set[str]:
        return {
            "Planner Agent",
            "Code Agent",
            "Database Agent",
            "Debug Agent",
            "Review Agent",
            "Project Agent",
            "Test Agent",
            "Deployment Agent",
            "Git Agent",
            "Frontend Agent",
            "Security Agent",
        }

    @staticmethod
    def _heuristic_route(message: str) -> dict[str, Any]:
        text = message.lower()
        if (
            text.count("\n") >= 2
            or len(text) >= 280
            or any(keyword in text for keyword in ("end-to-end", "multi-step", "multiple files", "with tests", "full application"))
        ):
            return {
                "agent": "Planner Agent",
                "reason": "The request contains multiple requirements and benefits from an explicit plan.",
                "confidence": 0.92,
            }
        rules = (
            (("security", "vulnerability", "cve", "secret", "authentication", "authorization", "permissions", "path traversal", "injection"), "Security Agent", "The request is security-sensitive or release-bound."),
            (("deploy", "deployment", "release", "publish", "package", "packaging", "pyinstaller", "docker"), "Deployment Agent", "The request explicitly asks for packaging or deployment."),
            (("git", "commit", "branch", "merge", "rebase", "push", "pull", "repository", "source control"), "Git Agent", "The request explicitly asks for source-control operations."),
            (("frontend", "html", "css", "javascript", "ui", "ux", "browser", "react", "alpine", "monaco"), "Frontend Agent", "The request explicitly affects frontend UI files."),
            (("sql", "database", "schema", "table", "query"), "Database Agent", "The request mentions database work."),
            (("debug", "bug", "error", "traceback", "exception", "failing"), "Debug Agent", "The request mentions a failure or debugging."),
            (("review", "audit", "refactor", "quality"), "Review Agent", "The request asks for review or quality analysis."),
            (("scaffold", "project structure", "bootstrap", "new project"), "Project Agent", "The request asks for project scaffolding."),
        )
        for keywords, agent, reason in rules:
            if any(keyword in text for keyword in keywords):
                return {"agent": agent, "reason": reason, "confidence": 0.86}
        return {"agent": "Code Agent", "reason": "The request is best handled as a coding task.", "confidence": 0.78}


def get_agent_config(
    current_agent: str,
    active_skills: Iterable[str] | None = None,
    active_tools: Iterable[str] | None = None,
    mcp_emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> AgentConfig:
    """Build the current agent configuration with selected skill injection."""
    agent_name = _normalize_agent(current_agent)
    from .code_agent import CodeAgent
    from .database_agent import DatabaseAgent
    from .debug_agent import DebugAgent
    from .deployment_agent import DeploymentAgent
    from .frontend_agent import FrontendAgent
    from .git_agent import GitAgent
    from .project_agent import ProjectAgent
    from .planner_agent import PlannerAgent
    from .review_agent import ReviewAgent
    from .test_agent import TestAgent
    from .security_agent import SecurityAgent
    from ..tools.rag import CODEBASE_SEARCH_TOOL
    from ..tools.registry import tool_registry
    from ..mcp.runtime import mcp_client_manager

    mcp_schemas, mcp_functions = mcp_client_manager.agent_tool_definitions(mcp_emit)
    selected_tool_schemas, selected_tool_functions = tool_registry.get_active_config(active_tools or [])

    if agent_name == "Orchestrator":
        tools = _merge_tool_schemas((HANDOFF_TOOL, CODEBASE_SEARCH_TOOL), [*selected_tool_schemas, *mcp_schemas])
        functions = _base_tool_functions()
        functions.update(selected_tool_functions)
        functions.update(mcp_functions)
        return AgentConfig("Orchestrator", Orchestrator.system_prompt, tuple(tools), functions)

    agent = {
        "Code Agent": CodeAgent,
        "Database Agent": DatabaseAgent,
        "Debug Agent": DebugAgent,
        "Project Agent": ProjectAgent,
        "Planner Agent": PlannerAgent,
        "Review Agent": ReviewAgent,
        "Test Agent": TestAgent,
        "Deployment Agent": DeploymentAgent,
        "Git Agent": GitAgent,
        "Frontend Agent": FrontendAgent,
        "Security Agent": SecurityAgent,
    }[agent_name]()
    from ..skills.registry import skill_registry

    skill_prompt, skill_schemas, skill_functions = skill_registry.get_active_config(list(active_skills or []))
    system_prompt = agent.system_prompt
    system_prompt = (
        f"{system_prompt} If another specialist is needed, call handoff with the next agent and reason. "
        "Preserve every explicit user requirement, including constraints about files, dependencies, formatting, "
        "and behavior. Do not add unrequested files or replace valid generated output with a starter template. "
        "Before every handoff, provide confidence from 0.0 to 1.0 and a specific reason. Populate "
        "handoff.state_update with the objective, current step, decisions, "
        "completed work, next actions, risks, artifacts, and any plan changes so the next specialist can continue "
        "without reconstructing the task from chat messages."
    )
    if agent_name in {"Code Agent", "Project Agent"}:
        system_prompt += " After implementation, hand off to Test Agent so the work is verified before completion."
    elif agent_name == "Test Agent":
        system_prompt += " You are the quality gate: create and execute tests before allowing completion."
    if skill_prompt:
        system_prompt = f"{system_prompt}\n\nActive skill instructions:\n{skill_prompt.rstrip()}"
    tools = _merge_tool_schemas(
        (HANDOFF_TOOL, *agent.tools, CODEBASE_SEARCH_TOOL),
        [*skill_schemas, *selected_tool_schemas, *mcp_schemas],
    )
    functions = _base_tool_functions()
    functions.update(skill_functions)
    functions.update(selected_tool_functions)
    functions.update(mcp_functions)
    return AgentConfig(agent_name, system_prompt, tuple(tools), functions)


def run_orchestration(
    user_message: str,
    context: Any,
    active_skills: list[str],
    socketio_emit: Callable[[str, dict[str, Any]], None],
    active_tools: list[str] | None = None,
    routing_hint: dict[str, Any] | None = None,
    client: Any = None,
    model: str = MODEL,
    max_handoffs: int = 8,
    cancel_event: threading.Event | None = None,
    metrics: dict[str, Any] | None = None,
) -> str:
    """Run the orchestrator-to-specialist handoff loop until text completes."""
    if client is None:
        task_state = TaskState.from_request(user_message, context, active_skills, active_tools)
        socketio_emit("agent_state", task_state.snapshot())
        orchestrator = Orchestrator()
        socketio_emit("agent_activity", {"type": "handoff", "to": "Orchestrator", "task_state": task_state.snapshot()})
        route = _routing_hint_route(routing_hint) or orchestrator.route(user_message)
        route_confidence = _normalize_confidence(route.get("confidence"))
        task_state.record_handoff("Orchestrator", route["agent"], route["reason"], confidence=route_confidence)
        if metrics is not None:
            metrics["agents"] = ["Orchestrator", route["agent"]]
            metrics["handoff_trace"] = list(task_state.handoff_history)
            metrics["task_state"] = task_state.snapshot()
        socketio_emit("agent_state", task_state.snapshot())
        socketio_emit(
            "agent_activity",
            {
                "type": "handoff",
                "to": route["agent"],
                "reason": route["reason"],
                "confidence": route_confidence,
                "task_state": task_state.snapshot(),
            },
        )
        skill_note = f" Active skills: {', '.join(active_skills)}." if active_skills else ""
        return (
            f"{route['agent']} selected.{skill_note} Configure OPENAI_API_KEY in backend/.env to enable the live model. "
            f"Request received: {user_message}"
        )

    task_state = TaskState.from_request(user_message, context, active_skills, active_tools)
    if metrics is not None:
        metrics["task_state"] = task_state.snapshot()
        metrics["handoff_trace"] = []
    socketio_emit("agent_state", task_state.snapshot())
    messages: list[dict[str, Any]] = [{"role": "system", "content": Orchestrator.system_prompt}]
    if isinstance(context, list):
        messages.extend(context)
    elif context:
        messages.append({"role": "system", "content": str(context)})
    messages.append({"role": "user", "content": user_message})
    current_agent = "Orchestrator"
    response_parts: list[str] = []

    handoff_count = 0
    handoff_limit = max(1, int(max_handoffs))
    while True:
        if cancel_event is not None and cancel_event.is_set():
            socketio_emit("agent_activity", {"type": "cancelled"})
            return "".join(response_parts)
        if handoff_count >= handoff_limit:
            socketio_emit("agent_error", {"error": "Maximum agent handoff limit reached"})
            return "".join(response_parts)
        handoff_count += 1
        agent_policy = get_agent_policy(current_agent)
        socketio_emit(
            "agent_activity",
            {
                "type": "handoff",
                "to": current_agent,
                "policy": {"token_budget": agent_policy.token_budget, "timeout_seconds": agent_policy.timeout_seconds, "retry_limit": agent_policy.retry_limit},
                "task_state": task_state.snapshot(),
            },
        )
        agent_config = get_agent_config(
            current_agent,
            active_skills,
            active_tools=active_tools,
            mcp_emit=socketio_emit,
        )
        messages[0] = {
            "role": "system",
            "content": f"{agent_config.system_prompt}\n\n{task_state.prompt_context()}",
        }
        cache_key = build_prompt_cache_key(
            agent_config.system_prompt,
            list(agent_config.tools),
            model=model,
            scope=f"agent-{current_agent.lower().replace(' ', '-')}",
        )
        turn_started_at = time.perf_counter()
        retry_count = 0
        for attempt in range(agent_policy.retry_limit + 1):
            try:
                response = _create_stream(
                    client,
                    model,
                    messages,
                    list(agent_config.tools),
                    token_budget=agent_policy.token_budget,
                    timeout_seconds=agent_policy.timeout_seconds,
                    cache_key=cache_key,
                )
                content, tool_calls, usage = _consume_stream(
                    response,
                    socketio_emit,
                    cancel_event,
                    deadline=time.monotonic() + agent_policy.timeout_seconds,
                )
                break
            except Exception as exc:
                if cancel_event is not None and cancel_event.is_set():
                    raise
                if attempt >= agent_policy.retry_limit:
                    raise
                retry_count += 1
                socketio_emit(
                    "agent_activity",
                    {
                        "type": "retry",
                        "agent": current_agent,
                        "attempt": retry_count,
                        "max_retries": agent_policy.retry_limit,
                        "error": str(exc),
                        "policy": {"token_budget": agent_policy.token_budget, "timeout_seconds": agent_policy.timeout_seconds, "retry_limit": agent_policy.retry_limit},
                    },
                )
                time.sleep(min(2**(attempt + 1), 4))
        if metrics is not None:
            metrics.setdefault("agent_turns", []).append(
                {
                    "agent_name": current_agent,
                    "execution_time_seconds": round(time.perf_counter() - turn_started_at, 3),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "cached_prompt_tokens": usage.get("cached_prompt_tokens", 0),
                    "retry_count": retry_count,
                    "token_budget": agent_policy.token_budget,
                    "timeout_seconds": agent_policy.timeout_seconds,
                }
            )
            metrics.setdefault("agent_retries", {})[current_agent] = metrics.setdefault("agent_retries", {}).get(current_agent, 0) + retry_count
            metrics["agent_policies"] = policy_snapshot()
            metrics["prompt_tokens"] = metrics.get("prompt_tokens", 0) + usage.get("prompt_tokens", 0)
            metrics["completion_tokens"] = metrics.get("completion_tokens", 0) + usage.get("completion_tokens", 0)
            metrics["total_tokens"] = metrics.get("total_tokens", 0) + usage.get("total_tokens", 0)
            metrics["cached_prompt_tokens"] = metrics.get("cached_prompt_tokens", 0) + usage.get("cached_prompt_tokens", 0)
            metrics["agents"] = [*metrics.get("agents", []), current_agent]
            metrics["task_state"] = task_state.snapshot()
        if content:
            response_parts.append(content)
        if cancel_event is not None and cancel_event.is_set():
            socketio_emit("agent_activity", {"type": "cancelled"})
            return "".join(response_parts)
        if not tool_calls:
            return "".join(response_parts)

        assistant_calls = _assistant_tool_calls(tool_calls)
        messages.append({"role": "assistant", "content": content or None, "tool_calls": assistant_calls})
        next_agent: str | None = None
        for call in assistant_calls:
            function_name = call["function"]["name"]
            arguments = call["function"]["arguments"]
            if _is_handoff(function_name):
                try:
                    arguments = json.dumps(parse_tool_arguments(function_name, arguments, agent_config.tools))
                except (StructuredOutputError, TypeError) as exc:
                    result = {"success": False, "error": str(exc)}
                    task_state.record_tool(function_name, result)
                    socketio_emit("agent_state", task_state.snapshot())
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps({"tool_result": result, "task_state": task_state.snapshot()}),
                        }
                    )
                    continue
                next_agent = _handoff_target(function_name, arguments)
                reason = _handoff_reason(arguments)
                confidence = _handoff_confidence(arguments)
                state_update = _handoff_state_update(arguments)
                task_state.record_handoff(current_agent, next_agent, reason, state_update, confidence)
                result = {
                    "success": True,
                    "handoff_to": next_agent,
                    "reason": reason,
                    "confidence": confidence,
                    "task_state": task_state.snapshot(),
                }
                if metrics is not None:
                    metrics["task_state"] = task_state.snapshot()
                    metrics["handoff_trace"] = list(task_state.handoff_history)
                socketio_emit("agent_state", task_state.snapshot())
                socketio_emit(
                    "agent_activity",
                    {
                        "type": "handoff",
                        "to": next_agent,
                        "reason": reason,
                        "confidence": confidence,
                        "task_state": task_state.snapshot(),
                    },
                )
            else:
                socketio_emit("agent_activity", {"type": "tool", "name": function_name, "agent": current_agent})
                result = _execute_tool(
                    function_name,
                    arguments,
                    socketio_emit,
                    agent_config.tool_functions,
                    cancel_event=cancel_event,
                    tool_schemas=agent_config.tools,
                )
                task_state.record_tool(function_name, result)
                socketio_emit("agent_state", task_state.snapshot())
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": json.dumps({"tool_result": result, "task_state": task_state.snapshot()}),
                }
            )
        if next_agent:
            current_agent = next_agent

def _create_stream(
    client: Any,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    token_budget: int | None = None,
    timeout_seconds: int | None = None,
    cache_key: str | None = None,
) -> Any:
    arguments = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": True,
    }
    if token_budget is not None:
        arguments["max_completion_tokens"] = token_budget
    if timeout_seconds is not None:
        arguments["timeout"] = timeout_seconds
    arguments.update(prompt_cache_arguments(cache_key))
    try:
        return client.chat.completions.create(**arguments, stream_options={"include_usage": True})
    except TypeError:
        arguments.pop("timeout", None)
        arguments.pop("max_completion_tokens", None)
        arguments.pop("prompt_cache_key", None)
        return client.chat.completions.create(**arguments)


def _consume_stream(
    response: Any,
    socketio_emit: Callable[[str, dict[str, Any]], None],
    cancel_event: threading.Event | None = None,
    deadline: float | None = None,
) -> tuple[str, dict[int, dict[str, str]], dict[str, int]]:
    content_parts: list[str] = []
    tool_calls: dict[int, dict[str, str]] = {}
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for chunk in response:
        if deadline is not None and time.monotonic() >= deadline:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            raise TimeoutError("Agent turn exceeded its timeout")
        if cancel_event is not None and cancel_event.is_set():
            close = getattr(response, "close", None)
            if callable(close):
                close()
            break
        raw_usage = getattr(chunk, "usage", None)
        if raw_usage is not None:
            for key in usage:
                usage[key] = int(getattr(raw_usage, key, 0) or 0)
            prompt_details = getattr(raw_usage, "prompt_tokens_details", None)
            cached_tokens = getattr(prompt_details, "cached_tokens", None) if prompt_details is not None else None
            if cached_tokens is not None:
                usage["cached_prompt_tokens"] = int(cached_tokens or 0)
        choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
        delta = getattr(choice, "delta", None)
        if delta is None:
            continue
        content = getattr(delta, "content", None) or ""
        if content:
            content_parts.append(content)
            socketio_emit("agent_message_chunk", {"content": content})
        for tool_call in getattr(delta, "tool_calls", None) or []:
            index = getattr(tool_call, "index", 0)
            entry = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            entry["id"] += getattr(tool_call, "id", None) or ""
            function = getattr(tool_call, "function", None)
            if function is not None:
                entry["name"] += getattr(function, "name", None) or ""
                entry["arguments"] += getattr(function, "arguments", None) or ""
    return "".join(content_parts), tool_calls, usage


def _assistant_tool_calls(tool_calls: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "id": call["id"] or f"call-{index}",
            "type": "function",
            "function": {"name": call["name"], "arguments": call["arguments"]},
        }
        for index, call in tool_calls.items()
    ]


def _is_handoff(function_name: str) -> bool:
    return function_name == "handoff" or function_name.startswith("handoff_to_")


def _handoff_target(function_name: str, arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        payload = {}
    candidate = payload.get("agent", "")
    if not candidate and function_name.startswith("handoff_to_"):
        candidate = function_name.removeprefix("handoff_to_").replace("_", " ")
    return _normalize_agent(candidate) if _normalize_agent(candidate) != "Orchestrator" else "Code Agent"


def _handoff_reason(arguments: str) -> str:
    try:
        payload = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return ""
    return str(payload.get("reason", ""))


def _handoff_confidence(arguments: str) -> float:
    try:
        payload = json.loads(arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        return _normalize_confidence(None)
    return _normalize_confidence(payload.get("confidence"))


def _normalize_confidence(value: Any, default: float = 0.5) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    return round(max(0.0, min(1.0, score)), 2)


def _handoff_state_update(arguments: str) -> dict[str, Any]:
    try:
        payload = json.loads(arguments or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    update = payload.get("state_update")
    return dict(update) if isinstance(update, dict) else {}


def _normalize_agent(agent_name: str) -> str:
    normalized = str(agent_name).strip().lower().replace("_", " ")
    aliases = {
        "orchestrator": "Orchestrator",
        "planner": "Planner Agent",
        "planner agent": "Planner Agent",
        "code": "Code Agent",
        "code agent": "Code Agent",
        "database": "Database Agent",
        "database agent": "Database Agent",
        "db": "Database Agent",
        "debug": "Debug Agent",
        "debug agent": "Debug Agent",
        "review": "Review Agent",
        "review agent": "Review Agent",
        "project": "Project Agent",
        "project agent": "Project Agent",
        "test": "Test Agent",
        "tester": "Test Agent",
        "test agent": "Test Agent",
        "deployment": "Deployment Agent",
        "deployment agent": "Deployment Agent",
        "deploy": "Deployment Agent",
        "git": "Git Agent",
        "git agent": "Git Agent",
        "source control": "Git Agent",
        "frontend": "Frontend Agent",
        "frontend agent": "Frontend Agent",
        "ui": "Frontend Agent",
        "security": "Security Agent",
        "security agent": "Security Agent",
        "security audit": "Security Agent",
    }
    return aliases.get(normalized, "Code Agent")


def _routing_hint_route(routing_hint: dict[str, Any] | None) -> dict[str, Any] | None:
    """Validate a local capability hint before using it without a live model."""
    if not isinstance(routing_hint, dict):
        return None
    candidate = str(routing_hint.get("agent", "")).strip()
    if candidate not in Orchestrator._valid_agents():
        return None
    reason = str(routing_hint.get("reason", "Capability recommendation.")).strip() or "Capability recommendation."
    return {
        "agent": candidate,
        "reason": reason,
        "confidence": _normalize_confidence(routing_hint.get("confidence"), default=0.75),
    }


def _merge_tool_schemas(base_schemas: tuple[dict, ...], skill_schemas: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[str] = set()
    for schema in [*base_schemas, *skill_schemas]:
        name = schema.get("function", {}).get("name") if isinstance(schema, dict) else None
        if name is None or name not in seen:
            merged.append(schema)
            if name:
                seen.add(name)
    return merged


def _base_tool_functions() -> dict[str, Callable[..., Any]]:
    from ..tools.code_exec import run_code
    from ..tools.database import db_connect, db_execute, db_execute_query, db_list_tables
    from ..tools.diagnostics import analyze_error
    from ..tools.deployment import request_deployment_approval
    from ..tools.file_ops import file_list, file_read, file_write
    from ..tools.git_agent import git_action, git_diff, git_history, git_status
    from ..tools.presentation import present_code
    from ..tools.project import scaffold_project
    from ..tools.memory import memory_save, memory_search, preference_update
    from ..tools.rag import codebase_search
    from ..tools.planning import create_plan
    from ..tools.test_runner import run_tests

    return {
        "file_read": file_read,
        "file_write": file_write,
        "file_list": file_list,
        "run_code": run_code,
        "present_code": present_code,
        "db_connect": db_connect,
        "db_execute": db_execute,
        "db_list_tables": db_list_tables,
        "db_execute_query": db_execute_query,
        "analyze_error": analyze_error,
        "request_deployment_approval": request_deployment_approval,
        "git_status": git_status,
        "git_diff": git_diff,
        "git_history": git_history,
        "git_action": git_action,
        "scaffold_project": scaffold_project,
        "memory_save": memory_save,
        "memory_search": memory_search,
        "preference_update": preference_update,
        "codebase_search": codebase_search,
        "create_plan": create_plan,
        "run_tests": run_tests,
    }


def _execute_tool(
    name: str,
    arguments: str,
    socketio_emit: Callable[[str, dict[str, Any]], None],
    tool_functions: dict[str, Callable[..., Any]],
    cancel_event: threading.Event | None = None,
    tool_schemas: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        parsed = parse_tool_arguments(name, arguments, tool_schemas or ())
    except (StructuredOutputError, TypeError) as exc:
        return {"success": False, "error": str(exc)}
    function = tool_functions.get(name)
    if function is None:
        function = _base_tool_functions().get(name)
    if function is None:
        return {"success": False, "error": f"Unknown tool: {name}"}
    if name == "present_code":
        parsed["emit_event"] = socketio_emit
    elif name == "create_plan":
        parsed["emit_event"] = socketio_emit
    elif name in {"db_execute", "db_execute_query"}:
        parsed["emit_event"] = socketio_emit
        parsed["cancel_event"] = cancel_event
    elif name in {"git_action", "request_deployment_approval"}:
        parsed["emit_event"] = socketio_emit
        parsed["cancel_event"] = cancel_event
    try:
        result = function(**parsed)
        if name == "file_write" and isinstance(result, dict) and result.get("success"):
            socketio_emit("workspace_file_changed", {"path": result.get("path", parsed.get("path", ""))})
        elif name == "scaffold_project" and isinstance(result, dict) and result.get("success"):
            for requested_path, file_result in result.get("files", {}).items():
                if isinstance(file_result, dict) and file_result.get("success"):
                    socketio_emit(
                        "workspace_file_changed",
                        {"path": file_result.get("path", requested_path)},
                    )
        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)}
