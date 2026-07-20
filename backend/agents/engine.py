"""OpenAI-backed agent execution and streamed tool calling."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from openai import OpenAI

from ..config import MODEL, OPENAI_API_KEY, PROMPT_CACHE_ENABLED
from ..skills.registry import SkillRegistry, skill_registry
from ..tools.registry import tool_registry
from ..tools.code_exec import run_code
from ..tools.database import db_connect, db_execute, db_execute_query, db_list_tables
from ..tools.deployment import request_deployment_approval
from ..tools.diagnostics import analyze_error
from ..tools.file_ops import file_list, file_read, file_write
from ..tools.git_agent import git_action, git_diff, git_history, git_status
from ..tools.presentation import present_code
from ..tools.project import scaffold_project
from ..tools.memory import memory_save, memory_search, preference_update
from ..tools.rag import codebase_search
from ..tools.planning import create_plan
from ..tools.test_runner import run_tests
from ..memory.agent_metrics import agent_performance_store
from .code_agent import CodeAgent
from .capabilities import CapabilityRouter
from .deployment_agent import DeploymentAgent
from .frontend_agent import FrontendAgent
from .git_agent import GitAgent
from .database_agent import DatabaseAgent
from .debug_agent import DebugAgent
from .orchestrator import Orchestrator, run_orchestration
from .project_agent import ProjectAgent
from .planner_agent import PlannerAgent
from .review_agent import ReviewAgent
from .test_agent import TestAgent
from .security_agent import SecurityAgent
from .policy import policy_snapshot
from .prompt_cache import build_prompt_cache_key, prompt_cache_arguments
from .structured_output import StructuredOutputError, parse_tool_arguments


EventEmitter = Callable[[str, dict[str, Any]], None]


class AgentEngine:
    """Coordinate routing, specialist execution, tools, and streamed events."""

    def __init__(
        self,
        client: Any = None,
        model: str = MODEL,
        registry: SkillRegistry | None = None,
        capability_router: CapabilityRouter | None = None,
    ) -> None:
        self.model = model
        self.client = client if client is not None else self._create_client()
        self.skill_registry = registry or skill_registry
        self.capability_router = capability_router or CapabilityRouter()
        self.orchestrator = Orchestrator()
        self.agents = {
            "Code Agent": CodeAgent(),
            "Database Agent": DatabaseAgent(),
            "Debug Agent": DebugAgent(),
            "Review Agent": ReviewAgent(),
            "Project Agent": ProjectAgent(),
            "Planner Agent": PlannerAgent(),
            "Test Agent": TestAgent(),
            "Deployment Agent": DeploymentAgent(),
            "Git Agent": GitAgent(),
            "Frontend Agent": FrontendAgent(),
            "Security Agent": SecurityAgent(),
        }

    @staticmethod
    def _create_client() -> Any:
        if not OPENAI_API_KEY or OPENAI_API_KEY == "your_key_here":
            return None
        return OpenAI(api_key=OPENAI_API_KEY)

    def run(
        self,
        message: str,
        emit_event: EventEmitter,
        skill_ids: list[str] | None = None,
        tool_ids: list[str] | None = None,
        auto_capabilities: bool = True,
        max_handoffs: int = 8,
        project_path: str = "",
        cancel_event: threading.Event | None = None,
        request_id: str = "",
    ) -> str:
        """Run one request and emit thinking, chunks, completion, or errors."""
        started_at = time.perf_counter()
        metrics: dict[str, Any] = {
            "model": self.model,
            "request_id": request_id,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_prompt_tokens": 0,
            "prompt_cache_enabled": PROMPT_CACHE_ENABLED,
            "agents": [],
            "agent_policies": policy_snapshot(),
        }
        status = "success"
        error_message = ""
        selected_skill_ids = skill_ids or []
        selected_tool_ids = tool_ids or []
        recommendation = self.capability_router.recommend(message) if auto_capabilities else None
        recommended_skill_ids = list(recommendation.skills) if recommendation else []
        recommended_tool_ids = list(recommendation.tools) if recommendation else []
        active_skill_ids = [
            skill_id
            for skill_id in dict.fromkeys([*selected_skill_ids, *recommended_skill_ids])
            if self.skill_registry.get(skill_id)
        ]
        active_tool_ids = [
            tool_id
            for tool_id in dict.fromkeys([*selected_tool_ids, *recommended_tool_ids])
            if tool_registry.get(tool_id)
        ]
        if recommendation:
            recommendation_payload = recommendation.public()
            recommendation_payload.update(
                {
                    "enabled": True,
                    "applied_skills": active_skill_ids,
                    "applied_tools": active_tool_ids,
                }
            )
            metrics["capability_recommendation"] = recommendation_payload
            emit_event("capability_recommendation", recommendation_payload)
        else:
            emit_event("capability_recommendation", {"enabled": False})
        emit_event("agent_activity", {"type": "thinking"})
        if active_skill_ids:
            emit_event("agent_activity", {"type": "skills", "skills": active_skill_ids})
        if active_tool_ids:
            emit_event("agent_activity", {"type": "tools", "tools": active_tool_ids})

        try:
            context = []
            if recommendation:
                context.append(
                    {
                        "role": "system",
                        "content": (
                            "Capability routing recommendation: route first to "
                            f"{recommendation.agent} because {recommendation.reason} "
                            "Treat this as a least-privilege routing hint and only choose another specialist "
                            "when the user request clearly requires it."
                        ),
                    }
                )
            if project_path:
                context.append(
                    {
                        "role": "system",
                        "content": (
                            f"Active project: {project_path}. Write all generated files inside this project. "
                            f"The primary entry point is {project_path}/main.py. Preserve the user's complete request "
                            "verbatim and do not replace valid model output with a generic starter template."
                        ),
                    }
                )
            response = run_orchestration(
                user_message=message,
                context=context,
                active_skills=active_skill_ids,
                active_tools=active_tool_ids,
                routing_hint=recommendation.public() if recommendation else None,
                socketio_emit=emit_event,
                client=self.client,
                model=self.model,
                max_handoffs=max_handoffs,
                cancel_event=cancel_event,
                metrics=metrics,
            )
            if self.client is None and not (cancel_event and cancel_event.is_set()):
                self._emit_chunks(response, emit_event)
            if cancel_event is not None and cancel_event.is_set():
                status = "cancelled"
                emit_event("agent_cancelled", {"model": self.model})
            else:
                emit_event("agent_message_complete", {"content": response})
            return response
        except Exception as exc:
            status = "error"
            error_message = str(exc)
            emit_event("agent_error", {"error": str(exc)})
            return ""
        finally:
            metrics["status"] = status
            metrics["error"] = error_message
            metrics["execution_time_seconds"] = round(time.perf_counter() - started_at, 3)
            metrics["agent_trace"] = list(dict.fromkeys(metrics.get("agents", [])))
            try:
                metrics["performance"] = agent_performance_store.record_run(
                    metrics,
                    request_id=request_id,
                    status=status,
                    error=error_message,
                )
            except Exception as exc:
                metrics["performance_error"] = str(exc)
            emit_event("agent_metrics", metrics)

    @staticmethod
    def _fallback_response(agent_name: str, message: str, active_skill_ids: list[str]) -> str:
        skill_note = f" Active skills: {', '.join(active_skill_ids)}." if active_skill_ids else ""
        return (
            f"{agent_name} selected.{skill_note} Configure OPENAI_API_KEY in backend/.env to enable the live model. "
            f"Request received: {message}"
        )

    @staticmethod
    def _emit_chunks(content: str, emit_event: EventEmitter, chunk_size: int = 80) -> None:
        for start in range(0, len(content), chunk_size):
            emit_event("agent_message_chunk", {"content": content[start : start + chunk_size]})

    def _run_specialist(
        self,
        agent: Any,
        message: str,
        emit_event: EventEmitter,
        skill_prompt: str,
        skill_schemas: list[dict],
        skill_functions: dict[str, Any],
    ) -> str:
        system_prompt = agent.system_prompt
        if skill_prompt:
            system_prompt = f"{system_prompt}\n\nActive skill instructions:\n{skill_prompt.rstrip()}"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]
        tools = self._merge_tool_schemas(agent.tools, skill_schemas)
        functions = self._base_tool_functions(emit_event)
        functions.update(skill_functions)
        return self._stream_completion(messages, tools, functions, emit_event)

    def _stream_completion(
        self,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict],
        tool_functions: dict[str, Any],
        emit_event: EventEmitter,
        round_number: int = 0,
    ) -> str:
        cache_key = build_prompt_cache_key(
            str(messages[0].get("content", "")) if messages else "",
            tool_schemas,
            model=self.model,
            scope="engine-specialist",
        )
        arguments = {
            "model": self.model,
            "messages": messages,
            "tools": tool_schemas,
            "tool_choice": "auto",
            "stream": True,
            **prompt_cache_arguments(cache_key),
        }
        try:
            response = self.client.chat.completions.create(**arguments)
        except TypeError:
            arguments.pop("prompt_cache_key", None)
            response = self.client.chat.completions.create(**arguments)
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}

        for chunk in response:
            choice = chunk.choices[0] if getattr(chunk, "choices", None) else None
            delta = getattr(choice, "delta", None)
            if delta is None:
                continue
            content = getattr(delta, "content", None) or ""
            if content:
                content_parts.append(content)
                emit_event("agent_message_chunk", {"content": content})
            for tool_call in getattr(delta, "tool_calls", None) or []:
                index = getattr(tool_call, "index", 0)
                function = getattr(tool_call, "function", None)
                entry = tool_calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                entry["id"] += getattr(tool_call, "id", None) or ""
                if function is not None:
                    entry["name"] += getattr(function, "name", None) or ""
                    entry["arguments"] += getattr(function, "arguments", None) or ""

        if tool_calls and round_number < 2:
            assistant_calls = [
                {
                    "id": call["id"],
                    "type": "function",
                    "function": {"name": call["name"], "arguments": call["arguments"]},
                }
                for call in tool_calls.values()
            ]
            messages.append({"role": "assistant", "content": "" or None, "tool_calls": assistant_calls})
            for call in assistant_calls:
                emit_event("agent_activity", {"type": "tool", "name": call["function"]["name"]})
                result = self._execute_tool(
                    call["function"]["name"],
                    call["function"]["arguments"],
                    emit_event,
                    tool_functions,
                    tool_schemas=tool_schemas,
                )
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
            return self._stream_completion(messages, tool_schemas, tool_functions, emit_event, round_number + 1)

        return "".join(content_parts)

    @staticmethod
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

    @staticmethod
    def _base_tool_functions(emit_event: EventEmitter) -> dict[str, Any]:
        return {
            "file_read": file_read,
            "file_write": file_write,
            "file_list": file_list,
            "run_code": run_code,
            "present_code": lambda **kwargs: present_code(emit_event=emit_event, **kwargs),
            "db_connect": db_connect,
            "db_execute": db_execute,
            "db_list_tables": db_list_tables,
            "db_execute_query": db_execute_query,
            "analyze_error": analyze_error,
            "request_deployment_approval": lambda **kwargs: request_deployment_approval(**kwargs),
            "git_status": git_status,
            "git_diff": git_diff,
            "git_history": git_history,
            "git_action": git_action,
            "scaffold_project": scaffold_project,
            "memory_save": memory_save,
            "memory_search": memory_search,
            "preference_update": preference_update,
            "codebase_search": codebase_search,
            "create_plan": lambda **kwargs: create_plan(emit_event=emit_event, **kwargs),
            "run_tests": run_tests,
        }

    @staticmethod
    def _execute_tool(
        name: str,
        arguments: str,
        emit_event: EventEmitter,
        tool_functions: dict[str, Any] | None = None,
        tool_schemas: list[dict] | None = None,
    ) -> dict[str, Any]:
        try:
            parsed = parse_tool_arguments(name, arguments, tool_schemas or ())
        except (StructuredOutputError, TypeError) as exc:
            return {"success": False, "error": str(exc)}

        functions = AgentEngine._base_tool_functions(emit_event)
        functions.update(tool_functions or {})
        function = functions.get(name)
        if function is None:
            return {"success": False, "error": f"Unknown tool: {name}"}
        try:
            if name == "file_write":
                from ..change_review import change_review_manager

                result = change_review_manager.request(parsed["path"], parsed["content"], emit_event)
            elif name == "create_plan":
                result = create_plan(emit_event=emit_event, **parsed)
            elif name in {"db_execute", "db_execute_query"}:
                result = function(emit_event=emit_event, **parsed)
            elif name in {"git_action", "request_deployment_approval"}:
                result = function(emit_event=emit_event, **parsed)
            else:
                result = function(**parsed)
            if name == "file_write" and result.get("success"):
                emit_event("workspace_file_changed", {"path": result.get("path", parsed.get("path", ""))})
            elif name == "scaffold_project" and result.get("success"):
                for requested_path, file_result in result.get("files", {}).items():
                    if isinstance(file_result, dict) and file_result.get("success"):
                        emit_event(
                            "workspace_file_changed",
                            {"path": file_result.get("path", requested_path)},
                        )
            return result
        except Exception as exc:
            return {"success": False, "error": str(exc)}
