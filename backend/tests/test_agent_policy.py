from types import SimpleNamespace

from backend.agents.orchestrator import run_orchestration
from backend.agents.policy import AGENT_POLICIES, get_agent_policy


def test_every_agent_has_two_retries_and_bounded_policy():
    assert AGENT_POLICIES
    for agent_name, policy in AGENT_POLICIES.items():
        assert get_agent_policy(agent_name).retry_limit == 2
        assert policy.token_budget > 0
        assert policy.timeout_seconds > 0


def test_orchestration_retries_transient_turn_failure_once():
    class Completions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                raise RuntimeError("temporary provider failure")
            return iter(
                [
                    SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content="completed", tool_calls=None))],
                        usage=None,
                    )
                ]
            )

    completions = Completions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    events = []
    metrics = {}

    result = run_orchestration(
        "Write a small script",
        [],
        [],
        lambda event, payload: events.append((event, payload)),
        client=client,
        metrics=metrics,
    )

    assert result == "completed"
    retry_events = [payload for event, payload in events if event == "agent_activity" and payload.get("type") == "retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["attempt"] == 1
    assert completions.calls[1]["max_completion_tokens"] == AGENT_POLICIES["Orchestrator"].token_budget
    assert completions.calls[1]["timeout"] == AGENT_POLICIES["Orchestrator"].timeout_seconds
    assert metrics["agent_turns"][0]["retry_count"] == 1
