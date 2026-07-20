"""Flask and Flask-SocketIO application for Mighty Coding Machine (MCM)."""

from __future__ import annotations

import threading
from uuid import uuid4
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO

from .agents.engine import AgentEngine
from .memory.agent_metrics import agent_performance_store
from .approval import approval_manager, approval_scope, shell_approval_level
from .change_review import change_review_manager
from .config import APPLICATION_PATH, MODEL, OPENAI_API_KEY, WORKSPACE_PATH, WORKSPACE_ROOT
from .exceptions import CMException
from .project_manager import create_project, is_generation_request
from .skills.registry import skill_registry
from .security import validate_path
from .tools.database import db_connect, db_execute_query, db_list_tables
from .tools.file_ops import project_scope
from .tools.terminal import TerminalSession
from .tools.rag import codebase_search
from .tools.registry import tool_registry
from .rag.indexer import workspace_indexer
from .tools.source_control import source_control
from .mcp.runtime import mcp_client_manager


PROJECT_DIR = Path(APPLICATION_PATH)
FRONTEND_DIR = PROJECT_DIR / "frontend"


def create_app(application_path: str | Path = APPLICATION_PATH) -> Flask:
    """Create and configure the Flask application."""
    frontend_dir = Path(application_path) / "frontend"
    application = Flask(__name__, static_folder=None)
    application.config.update(
        OPENAI_API_KEY=OPENAI_API_KEY,
        MODEL=MODEL,
        WORKSPACE_ROOT=WORKSPACE_ROOT,
    )

    @application.errorhandler(CMException)
    def handle_cm_exception(error: CMException) -> Any:
        return jsonify({"error": str(error)}), getattr(error, "status_code", 500)

    @application.get("/")
    def index() -> Any:
        return send_from_directory(frontend_dir, "index.html")

    @application.get("/<path:filename>")
    def frontend_file(filename: str) -> Any:
        return send_from_directory(frontend_dir, filename)

    @application.get("/health")
    def health() -> Any:
        return jsonify({"status": "ok", "service": "coding-machine"})

    @application.get("/api/skills")
    def skills() -> Any:
        return jsonify({"skills": skill_registry.public_definitions()})

    @application.get("/api/tools")
    def tools() -> Any:
        return jsonify({"tools": tool_registry.public_definitions()})

    @application.get("/api/mcp/servers")
    def mcp_servers() -> Any:
        return jsonify({"servers": mcp_client_manager.list_servers()})

    @application.get("/api/workspace/tree")
    def workspace_tree() -> Any:
        relative_path = str(request.args.get("path", ""))
        try:
            target = Path(validate_path(relative_path, WORKSPACE_PATH))
            if not target.is_dir():
                return jsonify({"success": False, "error": "Workspace path is not a folder", "items": []}), 400

            items = [
                {
                    "name": item.name,
                    "path": item.relative_to(WORKSPACE_PATH).as_posix(),
                    "is_dir": item.is_dir(),
                }
                for item in sorted(target.iterdir(), key=lambda item: item.name.lower())
            ]
            return jsonify({"success": True, "items": items})
        except (OSError, PermissionError, ValueError) as exc:
            return jsonify({"success": False, "error": str(exc), "items": []}), 400

    return application


app = create_app(APPLICATION_PATH)
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")
terminal_sessions: dict[str, tuple[TerminalSession, str]] = {}
terminal_sessions_lock = threading.Lock()
agent_runs: dict[str, tuple[str, threading.Event]] = {}
agent_runs_lock = threading.Lock()
indexing_state: dict[str, Any] = {
    "status": "idle",
    "current": 0,
    "total": 0,
    "indexed": 0,
    "skipped": 0,
    "errors": [],
}
indexing_state_lock = threading.RLock()
indexing_run_lock = threading.Lock()


def _update_indexing_state(payload: dict[str, Any]) -> None:
    with indexing_state_lock:
        indexing_state.update(payload)


def start_workspace_indexing(
    file_types: list[str] | None = None,
    incremental: bool = True,
    client_sid: str | None = None,
) -> bool:
    if not indexing_run_lock.acquire(blocking=False):
        with indexing_state_lock:
            payload = {**indexing_state, "message": "Indexing is already in progress."}
        if client_sid:
            socketio.emit("indexing_status", payload, to=client_sid)
        return False

    def emit(event: str, payload: dict[str, Any]) -> None:
        _update_indexing_state(payload)
        if client_sid:
            socketio.emit(event, payload, to=client_sid)
        else:
            socketio.emit(event, payload)

    def run_index() -> None:
        try:
            emit("indexing_started", {"status": "started", "file_types": file_types or [], "incremental": incremental})

            def progress(payload: dict[str, Any]) -> None:
                emit("indexing_progress", {"status": "running", **payload})

            result = workspace_indexer.index_workspace(
                file_types=file_types,
                incremental=incremental,
                progress_callback=progress,
            )
            for error in result.get("errors", []):
                emit("indexing_error", {"status": "error", "error": error})
            emit("indexing_complete", {"status": "complete" if result.get("success") else "error", **result})
        except Exception as exc:
            emit("indexing_error", {"status": "error", "error": str(exc)})
            emit("indexing_complete", {"status": "error", "success": False, "error": str(exc)})
        finally:
            indexing_run_lock.release()

    try:
        socketio.start_background_task(run_index)
    except Exception:
        indexing_run_lock.release()
        raise
    return True


@socketio.on("connect")
def handle_connect() -> None:
    print("Client connected to MCM Backend")
    socketio.emit("agent_performance", agent_performance_store.snapshot(), to=request.sid)


@socketio.on("agent_performance_history")
def handle_agent_performance_history(data: Any = None) -> None:
    payload = data if isinstance(data, dict) else {}
    try:
        limit = int(payload.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    socketio.emit("agent_performance", agent_performance_store.snapshot(limit), to=request.sid)


@socketio.on("agent_message")
def handle_agent_message(message: Any) -> None:
    user_message = message.get("message") if isinstance(message, dict) else message
    skill_ids = message.get("skill_ids", []) if isinstance(message, dict) else []
    tool_ids = message.get("tool_ids", []) if isinstance(message, dict) else []
    auto_capabilities = message.get("auto_capabilities", True) if isinstance(message, dict) else True
    max_handoffs = message.get("max_handoffs", 8) if isinstance(message, dict) else 8
    active_project_path = message.get("active_project_path", "") if isinstance(message, dict) else ""
    requested_project_name = message.get("project_name", "") if isinstance(message, dict) else ""
    request_id = str(message.get("request_id", "")) if isinstance(message, dict) else ""
    try:
        max_handoffs = max(1, min(int(max_handoffs), 16))
    except (TypeError, ValueError):
        max_handoffs = 8
    if not isinstance(skill_ids, list):
        skill_ids = []
    if not isinstance(tool_ids, list):
        tool_ids = []
    if not isinstance(auto_capabilities, bool):
        auto_capabilities = True
    if not isinstance(user_message, str) or not user_message.strip():
        socketio.emit("agent_error", {"error": "A non-empty message is required"}, to=request.sid)
        return

    client_sid = request.sid
    request_id = request_id or uuid4().hex
    cancel_event = threading.Event()
    with agent_runs_lock:
        previous = agent_runs.get(client_sid)
        if previous is not None:
            previous[1].set()
        agent_runs[client_sid] = (request_id, cancel_event)

    def emit_to_client(event: str, payload: dict[str, Any]) -> None:
        socketio.emit(event, payload, to=client_sid)

    def run_agent_thread() -> None:
        try:
            project_path = ""
            if is_generation_request(user_message):
                project = create_project(user_message.strip(), str(requested_project_name).strip() or None)
                project_path = project.relative_path
                emit_to_client(
                    "project_created",
                    {"name": project.name, "path": project.relative_path, "main_file": project.main_file},
                )
            elif active_project_path:
                candidate = str(active_project_path).replace("\\", "/").strip("/")
                target = Path(validate_path(candidate, WORKSPACE_PATH))
                if not target.is_dir():
                    raise ValueError("Active project directory was not found")
                project_path = target.relative_to(WORKSPACE_PATH.resolve()).as_posix()

            with approval_scope(client_sid), project_scope(project_path):
                AgentEngine().run(
                    user_message.strip(),
                    emit_to_client,
                    skill_ids=[str(skill_id) for skill_id in skill_ids],
                    tool_ids=[str(tool_id) for tool_id in tool_ids],
                    auto_capabilities=auto_capabilities,
                    max_handoffs=max_handoffs,
                    project_path=project_path,
                    cancel_event=cancel_event,
                    request_id=request_id,
                )
            if project_path:
                main_file = WORKSPACE_PATH / project_path / "main.py"
                if main_file.is_file():
                    emit_to_client(
                        "workspace_file_ready",
                        {
                            "path": f"{project_path}/main.py",
                            "content": main_file.read_text(encoding="utf-8"),
                        },
                    )
        except Exception as exc:
            emit_to_client("agent_error", {"error": str(exc)})
        finally:
            with agent_runs_lock:
                active = agent_runs.get(client_sid)
                if active is not None and active[0] == request_id:
                    agent_runs.pop(client_sid, None)

    socketio.start_background_task(run_agent_thread)


@socketio.on("agent_cancel")
def handle_agent_cancel(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    client_sid = request.sid
    request_id = str(payload.get("request_id", ""))
    with agent_runs_lock:
        active = agent_runs.get(client_sid)
    if active is None or (request_id and active[0] != request_id):
        socketio.emit("agent_cancelled", {"request_id": request_id, "already_finished": True}, to=client_sid)
        return
    active[1].set()
    change_review_manager.cancel_for(active[1])
    approval_manager.cancel_for(active[1])
    socketio.emit("agent_cancel_requested", {"request_id": active[0]}, to=client_sid)


@socketio.on("diff_review_action")
def handle_diff_review_action(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    review_id = str(payload.get("review_id", ""))
    accepted = bool(payload.get("accepted", False))
    resolved = change_review_manager.resolve(review_id, accepted)
    socketio.emit(
        "code_diff_review_result",
        {"review_id": review_id, "accepted": accepted, "success": resolved},
        to=request.sid,
    )


@socketio.on("approval_action")
def handle_approval_action(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    approval_id = str(payload.get("approval_id", ""))
    approved = bool(payload.get("approved", False))
    confirmation_text = str(payload.get("confirmation_text", ""))
    resolved = approval_manager.resolve(
        approval_id,
        approved,
        confirmation_text=confirmation_text,
        owner_id=request.sid,
        rejection_reason="Approval rejected by user.",
    )
    socketio.emit(
        "approval_action_result",
        {"approval_id": approval_id, "approved": approved, "success": resolved},
        to=request.sid,
    )


@socketio.on("mcp_list_servers")
def handle_mcp_list_servers() -> None:
    try:
        response = {"success": True, "servers": mcp_client_manager.list_servers()}
    except Exception as exc:
        response = {"success": False, "servers": [], "error": f"Unable to load MCP servers: {exc}"}
    socketio.emit("mcp_servers", response, to=request.sid)


@socketio.on("mcp_configure_server")
def handle_mcp_configure_server(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    try:
        result = mcp_client_manager.configure(payload)
        response = {"success": True, "server": result, "servers": mcp_client_manager.list_servers()}
    except Exception as exc:
        response = {"success": False, "error": str(exc)}
    socketio.emit("mcp_configure_result", response, to=client_sid)


@socketio.on("mcp_connect")
def handle_mcp_connect(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    server_id = str(payload.get("server_id", "")).strip()

    def run_connect() -> None:
        try:
            with approval_scope(client_sid):
                result = mcp_client_manager.connect(
                    server_id,
                    emit_event=lambda event, event_payload: socketio.emit(event, event_payload, to=client_sid),
                )
        except Exception as exc:
            result = {"success": False, "server_id": server_id, "error": f"Unable to connect to MCP server: {exc}"}
        try:
            result["servers"] = mcp_client_manager.list_servers()
        except Exception:
            result.setdefault("servers", [])
        socketio.emit("mcp_connect_result", result, to=client_sid)

    socketio.start_background_task(run_connect)


@socketio.on("mcp_disconnect")
def handle_mcp_disconnect(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    server_id = str(payload.get("server_id", "")).strip()

    def run_disconnect() -> None:
        try:
            result = mcp_client_manager.disconnect(server_id)
        except Exception as exc:
            result = {"success": False, "server_id": server_id, "error": f"Unable to disconnect MCP server: {exc}"}
        try:
            result["servers"] = mcp_client_manager.list_servers()
        except Exception:
            result.setdefault("servers", [])
        socketio.emit("mcp_disconnect_result", result, to=client_sid)

    socketio.start_background_task(run_disconnect)


@socketio.on("mcp_list_tools")
def handle_mcp_list_tools(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    try:
        result = mcp_client_manager.list_tools(str(payload.get("server_id", "")).strip())
    except Exception as exc:
        result = {"success": False, "tools": [], "error": f"Unable to list MCP tools: {exc}"}
    socketio.emit("mcp_tools", result, to=request.sid)


@socketio.on("mcp_call_tool")
def handle_mcp_call_tool(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    arguments = payload.get("arguments", {})
    if isinstance(arguments, str):
        import json

        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            arguments = None
    if not isinstance(arguments, dict):
        socketio.emit("mcp_tool_result", {"success": False, "error": "Tool arguments must be a JSON object."}, to=client_sid)
        return

    def run_tool() -> None:
        server_id = str(payload.get("server_id", "")).strip()
        tool_name = str(payload.get("tool_name", "")).strip()
        try:
            with approval_scope(client_sid):
                result = mcp_client_manager.call_tool(
                    server_id,
                    tool_name,
                    arguments=arguments,
                    emit_event=lambda event, event_payload: socketio.emit(event, event_payload, to=client_sid),
                )
        except Exception as exc:
            result = {"success": False, "server_id": server_id, "tool": tool_name, "error": f"MCP tool call failed: {exc}"}
        socketio.emit("mcp_tool_result", result, to=client_sid)

    socketio.start_background_task(run_tool)


@socketio.on("db_connect")
def handle_db_connect(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}

    def run_connection() -> None:
        connection_id = str(payload.get("connection_id", ""))
        try:
            result = db_connect(
                connection_id,
                str(payload.get("db_type", "sqlite")),
                str(payload.get("connection_string", "")),
            )
        except Exception as exc:
            result = {"success": False, "connection_id": connection_id, "error": f"Unable to connect to database: {exc}"}
        socketio.emit("db_connection_result", result, to=client_sid)

    socketio.start_background_task(run_connection)


@socketio.on("codebase_search")
def handle_codebase_search(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    query = str(payload.get("query", "")).strip()
    file_types = payload.get("file_types", [])
    if not isinstance(file_types, list):
        file_types = []

    def run_search() -> None:
        try:
            result = codebase_search(query, file_types=file_types)
        except Exception as exc:
            result = {"success": False, "query": query, "results": [], "error": f"Codebase search failed: {exc}"}
        socketio.emit("codebase_search_results", result, to=client_sid)

    socketio.start_background_task(run_search)


@socketio.on("workspace_reindex")
def handle_workspace_reindex(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    file_types = payload.get("file_types", [])
    if not isinstance(file_types, list):
        file_types = []
    start_workspace_indexing(
        file_types=[str(file_type) for file_type in file_types],
        incremental=bool(payload.get("incremental", True)),
        client_sid=request.sid,
    )


@socketio.on("workspace_index_status")
def handle_workspace_index_status() -> None:
    with indexing_state_lock:
        payload = dict(indexing_state)
    socketio.emit("indexing_status", payload, to=request.sid)


@socketio.on("source_control_status")
def handle_source_control_status(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}

    def run_status() -> None:
        try:
            result = source_control.status(str(payload.get("project_path", "")))
        except Exception as exc:
            result = {"success": False, "available": False, "error": f"Unable to load source control status: {exc}"}
        result["request_id"] = payload.get("request_id")
        socketio.emit("source_control_status_result", result, to=client_sid)

    socketio.start_background_task(run_status)


@socketio.on("source_control_diff")
def handle_source_control_diff(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}

    def run_diff() -> None:
        try:
            result = source_control.diff(
                str(payload.get("path", "")),
                bool(payload.get("staged", False)),
                str(payload.get("project_path", "")),
            )
        except Exception as exc:
            result = {"success": False, "error": f"Unable to load source control diff: {exc}"}
        socketio.emit("source_control_diff_result", result, to=client_sid)

    socketio.start_background_task(run_diff)


@socketio.on("source_control_action")
def handle_source_control_action(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    action = str(payload.get("action", ""))

    def run_action() -> None:
        try:
            if action == "initialize":
                result = source_control.init(str(payload.get("project_path", "")))
            elif action == "switch_branch":
                result = source_control.switch_branch(
                    str(payload.get("branch", "")),
                    str(payload.get("project_path", "")),
                )
            elif action == "push":
                result = source_control.push(
                    str(payload.get("remote", "origin")),
                    str(payload.get("branch", "")),
                    str(payload.get("project_path", "")),
                )
            elif action == "pull":
                result = source_control.pull(
                    str(payload.get("remote", "origin")),
                    str(payload.get("branch", "")),
                    str(payload.get("project_path", "")),
                )
            elif action == "stage":
                result = source_control.stage(str(payload.get("path", "")), str(payload.get("project_path", "")))
            elif action == "unstage":
                result = source_control.unstage(str(payload.get("path", "")), str(payload.get("project_path", "")))
            elif action == "commit":
                result = source_control.commit(str(payload.get("message", "")), str(payload.get("project_path", "")))
            else:
                result = {"success": False, "error": "Unsupported source control action."}
        except Exception as exc:
            result = {"success": False, "error": f"Unable to complete source control action: {exc}"}
        socketio.emit("source_control_action_result", result, to=client_sid)

    socketio.start_background_task(run_action)


@socketio.on("source_control_history")
def handle_source_control_history(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}
    try:
        limit = max(1, min(int(payload.get("limit", 25) or 25), 100))
    except (TypeError, ValueError):
        limit = 25

    def run_history() -> None:
        try:
            result = source_control.history(
                str(payload.get("project_path", "")),
                limit,
            )
        except Exception as exc:
            result = {"success": False, "available": False, "history": [], "error": f"Unable to load source control history: {exc}"}
        socketio.emit("source_control_history_result", result, to=client_sid)

    socketio.start_background_task(run_history)


@socketio.on("db_list_tables")
def handle_db_list_tables(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}

    def run_table_listing() -> None:
        connection_id = str(payload.get("connection_id", ""))
        try:
            result = db_list_tables(connection_id)
        except Exception as exc:
            result = {"success": False, "connection_id": connection_id, "tables": [], "error": f"Unable to load database tables: {exc}"}
        socketio.emit("db_tables", result, to=client_sid)

    socketio.start_background_task(run_table_listing)


@socketio.on("db_execute_query")
def handle_db_execute_query(data: Any) -> None:
    client_sid = request.sid
    payload = data if isinstance(data, dict) else {}

    def run_query() -> None:
        connection_id = str(payload.get("connection_id", ""))
        try:
            with approval_scope(client_sid):
                result = db_execute_query(
                    connection_id,
                    str(payload.get("sql_query", "")),
                    emit_event=lambda event, event_payload: socketio.emit(event, event_payload, to=client_sid),
                )
        except Exception as exc:
            result = {"success": False, "connection_id": connection_id, "error": f"Unable to execute database query: {exc}"}
        socketio.emit("db_query_result", result, to=client_sid)

    socketio.start_background_task(run_query)


@socketio.on("terminal_open")
def handle_terminal_open(data: Any = None) -> None:
    client_sid = request.sid
    session_id = f"terminal-{uuid4().hex[:12]}"
    try:
        session = TerminalSession(session_id, socketio, client_sid=client_sid)
    except (OSError, ValueError) as exc:
        socketio.emit("terminal_error", {"error": str(exc)}, to=client_sid)
        return

    with terminal_sessions_lock:
        terminal_sessions[session_id] = (session, client_sid)
    socketio.emit("terminal_ready", {"session_id": session_id}, to=client_sid)


@socketio.on("terminal_input")
def handle_terminal_input(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    session_id = str(payload.get("session_id", ""))
    command = payload.get("command", "")
    client_sid = request.sid
    with terminal_sessions_lock:
        session_entry = terminal_sessions.get(session_id)

    if session_entry is None or session_entry[1] != client_sid:
        socketio.emit("terminal_error", {"session_id": session_id, "error": "Unknown terminal session"}, to=client_sid)
        return

    def run_command() -> None:
        try:
            with approval_scope(client_sid):
                approval = approval_manager.request(
                    category="shell",
                    action="run_command",
                    summary="Run a terminal command",
                    details=str(command),
                    emit_event=lambda event, event_payload: socketio.emit(event, event_payload, to=client_sid),
                    level=shell_approval_level(str(command)),
                )
                if not approval.get("approved"):
                    result = {
                        "success": False,
                        "requires_approval": True,
                        "level": approval.get("level", "confirm"),
                        "error": approval.get("message", "Terminal command was not approved."),
                    }
                else:
                    result = session_entry[0].write(str(command))
        except Exception as exc:
            result = {"success": False, "session_id": session_id, "error": f"Unable to execute terminal command: {exc}"}
        socketio.emit("terminal_command_result", result, to=client_sid)

    socketio.start_background_task(run_command)


@socketio.on("terminal_close")
def handle_terminal_close(data: Any) -> None:
    payload = data if isinstance(data, dict) else {}
    session_id = str(payload.get("session_id", ""))
    client_sid = request.sid
    with terminal_sessions_lock:
        session_entry = terminal_sessions.get(session_id)
        if session_entry is not None and session_entry[1] == client_sid:
            terminal_sessions.pop(session_id, None)
        else:
            session_entry = None

    if session_entry is None:
        socketio.emit("terminal_error", {"session_id": session_id, "error": "Unknown terminal session"}, to=client_sid)
        return

    result = session_entry[0].close()
    socketio.emit("terminal_closed", result, to=client_sid)


@socketio.on("disconnect")
def handle_disconnect() -> None:
    client_sid = request.sid
    approval_manager.cancel_owner(client_sid)
    with agent_runs_lock:
        active_agent = agent_runs.pop(client_sid, None)
    if active_agent is not None:
        active_agent[1].set()
        change_review_manager.cancel_for(active_agent[1])
        approval_manager.cancel_for(active_agent[1])
    with terminal_sessions_lock:
        owned_sessions = [
            terminal_sessions.pop(session_id)[0]
            for session_id, (_, owner_sid) in list(terminal_sessions.items())
            if owner_sid == client_sid
        ]
    for session in owned_sessions:
        session.close()


def start_server() -> None:
    """Run the Socket.IO server for the desktop webview."""
    socketio.run(app, port=5000, allow_unsafe_werkzeug=True)
