from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from backend.agents.orchestrator import Orchestrator, TaskState, _consume_stream, _create_stream
from backend.agents.prompt_cache import build_prompt_cache_key
from backend.agents.orchestrator import get_agent_config, _handoff_confidence, _handoff_state_update, _normalize_agent
from backend.change_review import ChangeReviewManager
from backend.rag.indexer import WorkspaceIndexer
from backend.tools.planning import create_plan
from backend.tools.test_runner import run_tests
from backend.skills.global_template import GLOBAL_CODING_TEMPLATE
from backend.skills.agent_templates import ROLE_PLAYBOOKS


class RecordingStore:
    def __init__(self):
        self.codebase = SimpleNamespace(count=lambda: 0)
        self.files = []

    def replace_code_file(self, file_path, chunks):
        self.files.append((file_path, chunks))
        return {"success": True, "file_path": file_path, "chunks": len(chunks)}

    def search_codebase(self, query, limit=5, where=None):
        return {"success": True, "query": query, "limit": limit, "where": where, "results": []}


def test_indexer_filters_types_and_skips_unchanged_files(tmp_path):
    store = RecordingStore()
    indexer = WorkspaceIndexer(tmp_path, store)
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    first = indexer.index_workspace(file_types=["py"], incremental=True)
    second = indexer.index_workspace(file_types=["py"], incremental=True)

    assert first["indexed"] == 1
    assert second["indexed"] == 0
    assert second["skipped"] == 1
    assert [path for path, _ in store.files] == ["main.py"]


def test_change_review_writes_only_after_acceptance(tmp_path, monkeypatch):
    import backend.change_review as review_module
    import backend.tools.file_ops as file_ops

    monkeypatch.setattr(review_module, "WORKSPACE_PATH", tmp_path)
    monkeypatch.setattr(file_ops, "WORKSPACE_PATH", tmp_path)
    manager = ChangeReviewManager(timeout_seconds=2)
    events = []
    result_holder = {}

    def request_change():
        result_holder["result"] = manager.request(
            "main.py",
            "print('accepted')\n",
            lambda event, payload: events.append((event, payload)),
        )

    thread = threading.Thread(target=request_change)
    thread.start()
    deadline = time.monotonic() + 1
    while not events and time.monotonic() < deadline:
        time.sleep(0.01)
    assert events[0][0] == "code_diff_review"
    assert not (tmp_path / "main.py").exists()

    assert manager.resolve(events[0][1]["review_id"], True)
    thread.join(timeout=1)
    assert result_holder["result"]["success"] is True
    assert (tmp_path / "main.py").read_text(encoding="utf-8") == "print('accepted')\n"


def test_stream_reports_usage_and_stops_on_cancel():
    cancel_event = threading.Event()
    usage = SimpleNamespace(prompt_tokens=4, completion_tokens=3, total_tokens=7)
    chunks = [
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="hello", tool_calls=None))], usage=None),
        SimpleNamespace(choices=[], usage=usage),
    ]
    content, tool_calls, metrics = _consume_stream(iter(chunks), lambda *_: None, cancel_event)

    assert content == "hello"
    assert tool_calls == {}
    assert metrics == {"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7}


def test_stream_reports_cached_prompt_tokens_when_provider_returns_them():
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=3,
        total_tokens=13,
        prompt_tokens_details=SimpleNamespace(cached_tokens=7),
    )
    chunks = [SimpleNamespace(choices=[], usage=usage)]
    _, _, metrics = _consume_stream(iter(chunks), lambda *_: None)

    assert metrics["cached_prompt_tokens"] == 7


def test_prompt_cache_key_is_stable_for_the_same_agent_prefix():
    tools = [{"type": "function", "function": {"name": "file_read"}}]
    first = build_prompt_cache_key("stable system prompt", tools, model="test-model")
    second = build_prompt_cache_key("stable system prompt", tools, model="test-model")
    changed = build_prompt_cache_key("changed system prompt", tools, model="test-model")

    assert first == second
    assert first != changed
    assert first.startswith("cm-agent-")


def test_create_stream_passes_explicit_prompt_cache_key():
    class CompletionClient:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=self)

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return iter(())

    client = CompletionClient()
    _create_stream(
        client,
        "test-model",
        [{"role": "system", "content": "stable prompt"}],
        [],
        cache_key="cm-test-key",
    )

    assert client.calls[0]["prompt_cache_key"] == "cm-test-key"


def test_planner_and_test_agents_are_registered_with_quality_tools():
    planner = get_agent_config("Planner Agent")
    tester = get_agent_config("Test Agent")
    planner_tools = {tool["function"]["name"] for tool in planner.tools}
    tester_tools = {tool["function"]["name"] for tool in tester.tools}

    assert _normalize_agent("planner") == "Planner Agent"
    assert _normalize_agent("tester") == "Test Agent"
    assert "create_plan" in planner_tools
    assert "run_tests" in tester_tools
    assert "handoff" in tester_tools


def test_conditional_specialists_route_only_for_matching_requests():
    expected_routes = {
        "Commit these changes to git": "Git Agent",
        "Deploy this release with PyInstaller": "Deployment Agent",
        "Improve the CSS and browser UI": "Frontend Agent",
        "Audit this authentication code for vulnerabilities": "Security Agent",
    }
    for message, agent_name in expected_routes.items():
        assert Orchestrator._heuristic_route(message)["agent"] == agent_name
        config = get_agent_config(agent_name)
        assert config.name == agent_name
        assert "handoff" in {tool["function"]["name"] for tool in config.tools}


def test_global_coding_template_is_applied_to_every_agent():
    agent_names = [
        "Orchestrator",
        "Planner Agent",
        "Code Agent",
        "Database Agent",
        "Debug Agent",
        "Review Agent",
        "Project Agent",
        "Test Agent",
    ]

    for agent_name in agent_names:
        assert GLOBAL_CODING_TEMPLATE in get_agent_config(agent_name).system_prompt


def test_role_playbook_is_applied_to_every_agent():
    for agent_name, playbook in ROLE_PLAYBOOKS.items():
        assert playbook in get_agent_config(agent_name).system_prompt


def test_structured_task_state_survives_handoff_and_tool_updates():
    state = TaskState.from_request(
        "Build a reliable greeting app",
        [{"role": "system", "content": "Active project: greeting_app. Write files there."}],
        ["python"],
    )
    state.apply_update({
        "constraints": ["Use the standard library"],
        "acceptance_criteria": ["The app prints a greeting"],
        "plan": {"title": "Greeting plan", "steps": ["Implement", "Test"]},
    })
    state.record_handoff(
        "Planner Agent",
        "Code Agent",
        "Implement the planned application",
        {"completed_work": ["Requirements captured"], "current_step": "Implement"},
        confidence=0.87,
    )
    state.record_tool("file_write", {"success": True, "path": "greeting_app/main.py"})

    snapshot = state.snapshot()
    assert snapshot["project_path"] == "greeting_app"
    assert snapshot["plan"]["title"] == "Greeting plan"
    assert snapshot["completed_work"] == ["Requirements captured"]
    assert snapshot["artifacts"] == [{"path": "greeting_app/main.py", "source": "file_write"}]
    assert snapshot["handoff_history"][0]["to"] == "Code Agent"
    assert snapshot["handoff_history"][0]["confidence"] == 0.87
    assert "STRUCTURED TASK STATE" in state.prompt_context()


def test_handoff_state_update_is_parsed_and_schema_exposes_it():
    arguments = '{"agent":"Code Agent","reason":"Implement","confidence":0.91,"state_update":{"current_step":"Implement","completed_work":["Planned"]}}'
    assert _handoff_state_update(arguments) == {"current_step": "Implement", "completed_work": ["Planned"]}
    assert _handoff_confidence(arguments) == 0.91
    handoff_schema = next(tool for tool in get_agent_config("Orchestrator").tools if tool["function"]["name"] == "handoff")
    assert "state_update" in handoff_schema["function"]["parameters"]["properties"]
    assert handoff_schema["function"]["parameters"]["properties"]["confidence"]["maximum"] == 1


def test_create_plan_emits_acceptance_criteria():
    events = []
    result = create_plan(
        "Reliable feature",
        ["Implement the feature", "Run verification"],
        ["Existing tests pass", "New behavior is covered"],
        risks=["External service unavailable"],
        emit_event=lambda event, payload: events.append((event, payload)),
    )

    assert result["success"] is True
    assert events[0][0] == "agent_plan"
    assert events[0][1]["acceptance_criteria"] == ["Existing tests pass", "New behavior is covered"]


def test_run_tests_is_scoped_to_workspace(tmp_path, monkeypatch):
    import backend.tools.file_ops as file_ops
    import backend.tools.test_runner as test_runner

    monkeypatch.setattr(file_ops, "WORKSPACE_PATH", tmp_path)
    monkeypatch.setattr(test_runner, "WORKSPACE_PATH", tmp_path)
    (tmp_path / "test_sample.py").write_text("def test_sample():\n    assert 2 + 2 == 4\n", encoding="utf-8")

    result = run_tests(["test_sample.py"], timeout=30)

    assert result["success"] is True
    assert result["returncode"] == 0
    assert "1 passed" in result["stdout"]
