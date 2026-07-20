"""Thread-safe MCP client management for optional external servers."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from hashlib import sha1
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlparse

from ..approval import ApprovalLevel, ApprovalManager, approval_manager
from ..config import PROJECT_DIR, WORKSPACE_PATH


MCPEventEmitter = Callable[[str, dict[str, Any]], None]
Transport = Literal["stdio", "streamable_http"]


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for one conditionally launched MCP server."""

    server_id: str
    name: str
    transport: Transport = "stdio"
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: str = ""
    url: str = ""
    env_keys: tuple[str, ...] = ()
    enabled: bool = False
    read_only: bool = True
    allowed_tools: tuple[str, ...] = ()
    timeout_seconds: float = 30.0

    def public(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {
            "server_id": self.server_id,
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": list(self.args),
            "cwd": self.cwd,
            "url": self.url,
            "env_keys": list(self.env_keys),
            "enabled": self.enabled,
            "read_only": self.read_only,
            "allowed_tools": list(self.allowed_tools),
            "timeout_seconds": self.timeout_seconds,
        }
        result.update(state or {})
        return result


@dataclass
class _MCPConnection:
    queue: asyncio.Queue[Any]
    task: asyncio.Task[Any]


def classify_mcp_tool(tool_name: str) -> tuple[str, ApprovalLevel]:
    """Classify a discovered tool conservatively before it is called."""
    normalized = str(tool_name or "").lower().replace("-", "_")
    if any(word in normalized for word in ("database", "db_", "sql", "query")):
        return "database", ApprovalLevel.CONFIRM
    if any(word in normalized for word in ("shell", "command", "execute", "run", "terminal", "deploy")):
        return "shell", ApprovalLevel.ELEVATED
    if any(word in normalized for word in ("delete", "remove", "destroy", "drop", "truncate", "format")):
        return "destructive", ApprovalLevel.ELEVATED
    if any(word in normalized for word in ("write", "create", "update", "edit", "modify", "commit", "push", "pull", "insert", "alter")):
        return "write", ApprovalLevel.CONFIRM
    return "read", ApprovalLevel.AUTOMATIC


class MCPClientManager:
    """Own long-lived MCP sessions without blocking Flask's worker threads."""

    def __init__(
        self,
        configs: list[MCPServerConfig] | None = None,
        approvals: ApprovalManager | None = None,
        log_path: str | Path | None = None,
    ) -> None:
        self.approvals = approvals or approval_manager
        self.log_path = Path(log_path) if log_path else WORKSPACE_PATH / "logs" / "mcp.log"
        self._configs: dict[str, MCPServerConfig] = {}
        self._states: dict[str, dict[str, Any]] = {}
        self._connections: dict[str, _MCPConnection] = {}
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_ready = threading.Event()
        self._loop_thread: threading.Thread | None = None
        self._register_configs(configs or [])

    def _register_configs(self, configs: list[MCPServerConfig]) -> None:
        with self._lock:
            for config in configs:
                self._configs[config.server_id] = config
                self._states.setdefault(
                    config.server_id,
                    {"status": "disabled" if not config.enabled else "configured", "tools": [], "error": ""},
                )

    def register(self, config: MCPServerConfig) -> None:
        self._register_configs([config])

    def list_servers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [config.public(self._states.get(config.server_id, {})) for config in self._configs.values()]

    def get_config(self, server_id: str) -> MCPServerConfig | None:
        with self._lock:
            return self._configs.get(str(server_id))

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Update a preset without accepting secrets from the browser."""
        server_id = str(payload.get("server_id", "")).strip()
        if not server_id:
            raise ValueError("MCP server_id is required")
        with self._lock:
            current = self._configs.get(server_id)
        if current is None:
            current = MCPServerConfig(server_id=server_id, name=server_id)

        transport = str(payload.get("transport", current.transport)).strip().lower()
        if transport not in {"stdio", "streamable_http"}:
            raise ValueError("MCP transport must be stdio or streamable_http")
        timeout = max(1.0, min(float(payload.get("timeout_seconds", current.timeout_seconds)), 300.0))
        url = str(payload.get("url", current.url)).strip()
        if transport == "streamable_http":
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("MCP HTTP servers require an http(s) URL")

        args = payload.get("args", list(current.args))
        if isinstance(args, str):
            args = args.split()
        if not isinstance(args, list):
            args = list(current.args)
        env_keys = payload.get("env_keys", list(current.env_keys))
        if isinstance(env_keys, str):
            env_keys = [item.strip() for item in env_keys.split(",") if item.strip()]
        if not isinstance(env_keys, list):
            env_keys = list(current.env_keys)
        allowed_tools = payload.get("allowed_tools", list(current.allowed_tools))
        if isinstance(allowed_tools, str):
            allowed_tools = [item.strip() for item in allowed_tools.split(",") if item.strip()]
        if not isinstance(allowed_tools, list):
            allowed_tools = list(current.allowed_tools)

        updated = replace(
            current,
            name=str(payload.get("name", current.name)).strip() or current.name,
            transport=transport,
            command=str(payload.get("command", current.command)).strip(),
            args=tuple(str(item) for item in args),
            cwd=str(payload.get("cwd", current.cwd)).strip(),
            url=url,
            env_keys=tuple(str(item) for item in env_keys),
            enabled=bool(payload.get("enabled", True)),
            read_only=bool(payload.get("read_only", current.read_only)),
            allowed_tools=tuple(str(item) for item in allowed_tools),
            timeout_seconds=timeout,
        )
        if updated.transport == "stdio" and not updated.command:
            raise ValueError("stdio MCP servers require a command")
        with self._lock:
            self._configs[server_id] = updated
            state = self._states.setdefault(server_id, {"tools": [], "error": ""})
            if state.get("status") == "disabled" and updated.enabled:
                state["status"] = "configured"
        self._log("configure", server_id=server_id, read_only=updated.read_only)
        return updated.public(self._states.get(server_id, {}))

    def connect(self, server_id: str, emit_event: MCPEventEmitter | None = None) -> dict[str, Any]:
        config = self.get_config(server_id)
        if config is None:
            return {"success": False, "error": f"Unknown MCP server: {server_id}"}
        if not config.enabled:
            return {"success": False, "error": f"MCP server '{server_id}' is disabled. Configure it first."}
        approval = self.approvals.request(
            category="mcp_server",
            action="launch_mcp_server",
            summary=f"Launch MCP server: {config.name}",
            details=self._launch_details(config),
            emit_event=emit_event,
            level=ApprovalLevel.CONFIRM,
        )
        if not approval.get("approved"):
            return {"success": False, "server_id": server_id, "error": approval.get("message", "MCP launch was not approved."), "requires_approval": True}
        try:
            result = self._run(self._connect_async(config), config.timeout_seconds + 5)
            self._log("connect", server_id=server_id, success=True)
            return {"success": True, **result}
        except TimeoutError:
            error = (
                f"MCP server '{config.name}' did not finish starting within {int(config.timeout_seconds)} seconds. "
                "Verify its runtime and network access, then try Connect again."
            )
            self._set_state(server_id, status="error", error=error)
            self._log("connect", server_id=server_id, success=False, error=error)
            return {"success": False, "server_id": server_id, "error": error}
        except Exception as exc:
            error = self._connection_error(config, exc)
            self._set_state(server_id, status="error", error=error)
            self._log("connect", server_id=server_id, success=False, error=error)
            return {"success": False, "server_id": server_id, "error": error}

    def disconnect(self, server_id: str) -> dict[str, Any]:
        try:
            self._run(self._disconnect_async(str(server_id)), 10)
            self._set_state(server_id, status="configured", error="", tools=[])
            self._log("disconnect", server_id=server_id, success=True)
            return {"success": True, "server_id": server_id}
        except Exception as exc:
            self._log("disconnect", server_id=server_id, success=False, error=str(exc))
            return {"success": False, "server_id": server_id, "error": str(exc)}

    def list_tools(self, server_id: str) -> dict[str, Any]:
        config = self.get_config(server_id)
        with self._lock:
            state = dict(self._states.get(str(server_id), {}))
        if config is None:
            return {"success": False, "error": f"Unknown MCP server: {server_id}"}
        return {"success": state.get("status") == "connected", "server_id": server_id, "tools": state.get("tools", []), "error": state.get("error", "")}

    def agent_tool_definitions(self, emit_event: MCPEventEmitter | None = None) -> tuple[list[dict[str, Any]], dict[str, Callable[..., Any]]]:
        """Expose only connected, permitted MCP tools as OpenAI functions."""
        schemas: list[dict[str, Any]] = []
        functions: dict[str, Callable[..., Any]] = {}
        with self._lock:
            configs = list(self._configs.values())
            states = {server_id: dict(state) for server_id, state in self._states.items()}
        for config in configs:
            state = states.get(config.server_id, {})
            if state.get("status") != "connected":
                continue
            for tool in state.get("tools", []):
                if not tool.get("allowed"):
                    continue
                original_name = str(tool.get("name", ""))
                if not original_name:
                    continue
                function_name = self._agent_function_name(config.server_id, original_name)
                parameters = tool.get("input_schema")
                if not isinstance(parameters, dict):
                    parameters = {"type": "object", "properties": {}}
                schemas.append(
                    {
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "description": f"MCP {config.name}: {tool.get('description', '')}".strip(),
                            "parameters": parameters,
                        },
                    }
                )
                functions[function_name] = self._agent_function(config.server_id, original_name, emit_event)
        return schemas, functions

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        emit_event: MCPEventEmitter | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        config = self.get_config(server_id)
        if config is None:
            return {"success": False, "error": f"Unknown MCP server: {server_id}"}
        with self._lock:
            state = self._states.get(server_id, {})
            known_tools = {item.get("name") for item in state.get("tools", [])}
        if state.get("status") != "connected":
            return {"success": False, "error": f"MCP server '{server_id}' is not connected."}
        if known_tools and tool_name not in known_tools:
            return {"success": False, "error": f"Tool '{tool_name}' was not discovered on '{server_id}'."}
        if config.allowed_tools and tool_name not in config.allowed_tools:
            return {"success": False, "error": f"Tool '{tool_name}' is not in the configured allow-list."}

        category, level = classify_mcp_tool(tool_name)
        if config.read_only and category != "read":
            return {"success": False, "server_id": server_id, "tool": tool_name, "blocked": True, "error": "This MCP server is configured read-only; the requested tool is blocked."}
        if category != "read":
            approval = self.approvals.request(
                category=f"mcp_{category}",
                action=f"mcp_{tool_name}",
                summary=f"Call MCP tool: {server_id}/{tool_name}",
                details=json.dumps(arguments or {}, ensure_ascii=True)[:4000],
                emit_event=emit_event,
                level=level,
                cancel_event=cancel_event,
            )
            if not approval.get("approved"):
                return {"success": False, "server_id": server_id, "tool": tool_name, "requires_approval": True, "error": approval.get("message", "MCP tool call was not approved.")}

        started = time.perf_counter()
        try:
            result = self._run(self._call_tool_async(server_id, tool_name, arguments or {}, config.timeout_seconds), config.timeout_seconds + 2)
            result.update({"server_id": server_id, "tool": tool_name})
            self._log("call", server_id=server_id, tool=tool_name, success=bool(result.get("success")), duration_seconds=round(time.perf_counter() - started, 3))
            return result
        except TimeoutError:
            self._log("call", server_id=server_id, tool=tool_name, success=False, error="timeout")
            return {"success": False, "server_id": server_id, "tool": tool_name, "error": "MCP tool call timed out."}
        except Exception as exc:
            self._log("call", server_id=server_id, tool=tool_name, success=False, error=str(exc))
            return {"success": False, "server_id": server_id, "tool": tool_name, "error": str(exc)}

    async def _connect_async(self, config: MCPServerConfig) -> dict[str, Any]:
        await self._disconnect_async(config.server_id)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        ready = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(self._session_main(config, queue, ready), name=f"cm-mcp-{config.server_id}")
        connection = _MCPConnection(queue=queue, task=task)
        with self._lock:
            self._connections[config.server_id] = connection
        try:
            return await asyncio.wait_for(ready, timeout=config.timeout_seconds)
        except Exception:
            await self._disconnect_async(config.server_id)
            raise

    @staticmethod
    def _official_sdk() -> tuple[Any, Any, Any, Any]:
        """Load the installed SDK even when pytest exposes ``backend/mcp`` first."""
        backend_path = Path(__file__).resolve().parents[1]
        removed_paths: list[str] = []
        for entry in list(sys.path):
            try:
                if Path(entry or ".").resolve() == backend_path:
                    sys.path.remove(entry)
                    removed_paths.append(entry)
            except OSError:
                continue
        try:
            local_module = sys.modules.get("mcp")
            local_file = getattr(local_module, "__file__", "")
            if local_file and Path(local_file).resolve().is_relative_to(backend_path / "mcp"):
                for name in [name for name in sys.modules if name == "mcp" or name.startswith("mcp.")]:
                    sys.modules.pop(name, None)
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
            from mcp.client.streamable_http import streamable_http_client

            return ClientSession, StdioServerParameters, stdio_client, streamable_http_client
        finally:
            for entry in reversed(removed_paths):
                sys.path.insert(0, entry)

    async def _disconnect_async(self, server_id: str) -> None:
        with self._lock:
            connection = self._connections.pop(server_id, None)
        if connection is not None:
            if connection.task.done():
                try:
                    connection.task.result()
                except (asyncio.CancelledError, Exception):
                    pass
                return
            completed = asyncio.get_running_loop().create_future()
            await connection.queue.put(("close", completed))
            await asyncio.wait_for(completed, timeout=8)
            await asyncio.wait_for(connection.task, timeout=8)

    async def _call_tool_async(self, server_id: str, tool_name: str, arguments: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        with self._lock:
            connection = self._connections.get(server_id)
        if connection is None:
            raise RuntimeError(f"MCP server '{server_id}' is not connected.")
        completed = asyncio.get_running_loop().create_future()
        await connection.queue.put(("call", tool_name, arguments, timeout_seconds, completed))
        return await asyncio.wait_for(completed, timeout=timeout_seconds)

    async def _session_main(self, config: MCPServerConfig, queue: asyncio.Queue[Any], ready: asyncio.Future[Any]) -> None:
        ClientSession, StdioServerParameters, stdio_client, streamable_http_client = self._official_sdk()
        try:
            if config.transport == "stdio":
                parameters = StdioServerParameters(
                    command=config.command,
                    args=list(config.args),
                    cwd=config.cwd or str(PROJECT_DIR),
                    env=self._stdio_environment(config),
                )
                transport = stdio_client(parameters)
            else:
                transport = streamable_http_client(config.url)
            async with transport as streams, ClientSession(streams[0], streams[1]) as session:
                await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
                tool_result = await asyncio.wait_for(session.list_tools(), timeout=config.timeout_seconds)
                tools = [self._public_tool(tool, config) for tool in tool_result.tools]
                with self._lock:
                    self._states[config.server_id] = {"status": "connected", "tools": tools, "error": ""}
                if not ready.done():
                    ready.set_result({"server_id": config.server_id, "status": "connected", "tools": tools})
                while True:
                    operation = await queue.get()
                    if operation[0] == "close":
                        if not operation[1].done():
                            operation[1].set_result(True)
                        return
                    _, tool_name, arguments, timeout_seconds, completed = operation
                    try:
                        result = await asyncio.wait_for(
                            session.call_tool(tool_name, arguments, read_timeout_seconds=timedelta(seconds=timeout_seconds)),
                            timeout=timeout_seconds,
                        )
                        content = [self._json_value(item) for item in (getattr(result, "content", None) or [])]
                        payload = {
                            "success": not bool(getattr(result, "isError", False)),
                            "is_error": bool(getattr(result, "isError", False)),
                            "content": content,
                            "structured_content": self._json_value(getattr(result, "structuredContent", None)),
                        }
                        if not completed.done():
                            completed.set_result(payload)
                    except Exception as exc:
                        if not completed.done():
                            completed.set_exception(exc)
        except Exception as exc:
            self._set_state(config.server_id, status="error", error=self._connection_error(config, exc))
            if not ready.done():
                ready.set_exception(exc)
        finally:
            with self._lock:
                self._connections.pop(config.server_id, None)

    @staticmethod
    def _public_tool(tool: Any, config: MCPServerConfig) -> dict[str, Any]:
        category, level = classify_mcp_tool(getattr(tool, "name", ""))
        return {
            "name": str(getattr(tool, "name", "")),
            "description": str(getattr(tool, "description", "") or ""),
            "input_schema": MCPClientManager._json_value(getattr(tool, "inputSchema", {}) or {}),
            "risk": category,
            "approval_level": level.value,
            "allowed": (not config.allowed_tools or getattr(tool, "name", "") in config.allowed_tools) and (not config.read_only or category == "read"),
        }

    @staticmethod
    def _json_value(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [MCPClientManager._json_value(item) for item in value]
        if isinstance(value, dict):
            return {str(key): MCPClientManager._json_value(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return MCPClientManager._json_value(value.model_dump(mode="json"))
        if hasattr(value, "text"):
            return {"type": "text", "text": str(value.text)}
        return str(value)

    @staticmethod
    def _agent_function_name(server_id: str, tool_name: str) -> str:
        raw = "mcp_" + "_".join("".join(character if character.isalnum() else "_" for character in value) for value in (server_id, tool_name))
        if len(raw) <= 64:
            return raw
        return f"{raw[:55]}_{sha1(raw.encode('utf-8')).hexdigest()[:8]}"

    def _agent_function(self, server_id: str, tool_name: str, emit_event: MCPEventEmitter | None) -> Callable[..., Any]:
        def call(**arguments: Any) -> dict[str, Any]:
            return self.call_tool(server_id, tool_name, arguments, emit_event=emit_event)

        return call

    def _run(self, coroutine: Any, timeout: float) -> Any:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        try:
            return future.result(timeout=max(1.0, timeout))
        except (TimeoutError, asyncio.TimeoutError):
            future.cancel()
            raise TimeoutError from None

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            self._loop_ready.clear()
            self._loop_thread = threading.Thread(target=self._loop_main, name="cm-mcp-loop", daemon=True)
            self._loop_thread.start()
        if not self._loop_ready.wait(5):
            raise RuntimeError("MCP client event loop failed to start")
        if self._loop is None:
            raise RuntimeError("MCP client event loop is unavailable")
        return self._loop

    def _loop_main(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        with self._lock:
            self._loop = loop
        self._loop_ready.set()
        loop.run_forever()
        loop.close()

    def _set_state(self, server_id: str, **values: Any) -> None:
        with self._lock:
            self._states.setdefault(server_id, {}).update(values)

    @staticmethod
    def _stdio_environment(config: MCPServerConfig) -> dict[str, str]:
        """Pass only inherited and explicitly allowed environment variables to external MCP runtimes."""
        configured = {key: os.environ[key] for key in config.env_keys if os.environ.get(key)}
        return {**os.environ, **configured}

    @staticmethod
    def _connection_error(config: MCPServerConfig, exc: BaseException) -> str:
        """Turn nested AnyIO startup errors into a concise, actionable MCP message."""
        leaf_messages: list[str] = []

        def collect(error: BaseException) -> None:
            if isinstance(error, BaseExceptionGroup):
                for nested in error.exceptions:
                    collect(nested)
                return
            detail = str(error).strip()
            leaf_messages.append(f"{type(error).__name__}: {detail}" if detail else type(error).__name__)

        collect(exc)
        details = "; ".join(dict.fromkeys(leaf_messages))
        if isinstance(exc, BaseExceptionGroup):
            message = f"MCP server '{config.name}' exited during startup"
            if details:
                message += f" ({details})"
            return f"{message}. Verify its command and network access, then try Connect again."
        return details or f"MCP server '{config.name}' could not be started."

    @staticmethod
    def _launch_details(config: MCPServerConfig) -> str:
        if config.transport == "streamable_http":
            return f"Connect to {config.url} with a {config.timeout_seconds}s timeout."
        return " ".join([config.command, *config.args])[:4000]

    def _log(self, action: str, **fields: Any) -> None:
        record = {"timestamp": time.time(), "action": action, **fields}
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")
        except OSError:
            logging.getLogger(__name__).warning("Unable to write MCP audit log")


__all__ = ["MCPClientManager", "MCPServerConfig", "classify_mcp_tool"]
