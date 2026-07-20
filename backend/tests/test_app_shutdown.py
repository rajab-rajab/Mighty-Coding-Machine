from __future__ import annotations

import importlib


class _FakeWindow:
    def __init__(self) -> None:
        self.scripts: list[str] = []
        self.destroyed = False

    def evaluate_js(self, script: str):
        self.scripts.append(script)
        return True if "Boolean(window.__mcmTrayShutdownReady)" in script else None

    def destroy(self) -> None:
        self.destroyed = True


def test_tray_shutdown_saves_session_before_destroying_window(mocker):
    desktop_app = importlib.import_module("app")
    window = _FakeWindow()
    mocker.patch.object(desktop_app.webview, "windows", [window])

    saved = desktop_app._shutdown_window_gracefully(timeout_seconds=0.1, poll_interval_seconds=0)

    assert saved is True
    assert window.destroyed is True
    assert any("cmSaveSessionBeforeExit" in script for script in window.scripts)
