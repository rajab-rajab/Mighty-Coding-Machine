from __future__ import annotations

from app import Api


def test_session_save_list_and_load(monkeypatch, tmp_path):
    monkeypatch.setattr("app.resolve_workspace_path", lambda path: tmp_path / path)
    api = Api()
    payload = {
        "session_id": "session-test-1",
        "name": "Test Session",
        "timestamp": "2026-07-17T00:00:00+00:00",
        "conversation_history": [
            {"role": "user", "content": "Hello"},
            {"role": "agent", "content": "Hi"},
        ],
        "model_name": "test-model",
        "project_path": "project",
        "current_workspace": "workspace",
        "conversation_metadata": {"message_count": 2},
    }

    saved = api.save_session(payload)
    assert saved["success"] is True
    assert (tmp_path / "sessions" / "session-test-1.cmsession").is_file()

    listed = api.list_sessions()
    assert listed["success"] is True
    assert listed["sessions"][0]["name"] == "Test Session"

    loaded = api.load_session("session-test-1")
    assert loaded == {"success": True, "session": {**payload, "updated_at": loaded["session"]["updated_at"]}}


def test_session_listing_reports_corrupt_json(monkeypatch, tmp_path):
    monkeypatch.setattr("app.resolve_workspace_path", lambda path: tmp_path / path)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "broken.cmsession").write_text("not json", encoding="utf-8")

    result = Api().list_sessions()

    assert result["success"] is True
    assert result["sessions"][0]["valid"] is False
    assert result["sessions"][0]["error"]


def test_preference_bridge_round_trip(monkeypatch):
    preferences = {}

    class PreferenceStub:
        def get(self, key, default=None):
            return preferences.get(key, default)

        def update(self, key, value):
            preferences[key] = value
            return {"success": True, "key": key, "value": value}

    monkeypatch.setattr("app.metadata_store", PreferenceStub())
    api = Api()

    saved = api.set_preference("theme", "dark")
    loaded = api.get_preference("theme", "colorful")

    assert saved == {"success": True, "key": "theme", "value": "dark"}
    assert loaded == {"success": True, "key": "theme", "value": "dark"}
