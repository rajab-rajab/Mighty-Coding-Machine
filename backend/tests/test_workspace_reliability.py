from __future__ import annotations

from backend import config
from backend.instance_lock import SingleInstanceLock


def test_workspace_override_round_trip(tmp_path, monkeypatch):
    override_file = tmp_path / "workspace-root.txt"
    selected = tmp_path / "selected-workspace"
    monkeypatch.setattr(config, "WORKSPACE_OVERRIDE_FILE", override_file)

    saved = config.save_workspace_root(selected)

    assert saved == str(selected.resolve())
    assert override_file.read_text(encoding="utf-8") == saved


def test_single_instance_lock_excludes_second_owner(tmp_path):
    lock_name = f"cm-test-{tmp_path.name}.lock"
    first = SingleInstanceLock(lock_name)
    second = SingleInstanceLock(lock_name)

    assert first.acquire() is True
    try:
        assert second.acquire() is False
    finally:
        first.release()

    assert second.acquire() is True
    second.release()
