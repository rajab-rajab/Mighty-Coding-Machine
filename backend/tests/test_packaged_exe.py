"""Opt-in smoke tests for the packaged Windows desktop executable."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SMOKE_ENABLED = os.name == "nt" and os.getenv("CM_RUN_EXE_SMOKE") == "1"
pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED,
    reason="Set CM_RUN_EXE_SMOKE=1 to run packaged EXE smoke tests on Windows.",
)


def _packaged_exe() -> Path:
    configured = os.getenv("CM_EXE_PATH", "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(PROJECT_ROOT / "dist-mcp" / "My MCM" / "My MCM.exe")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    pytest.fail("Packaged executable not found. Set CM_EXE_PATH to My MCM.exe.")


def _port_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", 5000))
        except OSError:
            return False
        return True


def _get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:5000{path}", timeout=5) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError:
        return 0, ""


@pytest.fixture(scope="module")
def packaged_app(tmp_path_factory):
    if not _port_available():
        pytest.skip("Port 5000 is already in use; close Coding Machine before the EXE smoke test.")

    executable = _packaged_exe()
    test_root = tmp_path_factory.mktemp("packaged-exe")
    workspace = test_root / "workspace"
    workspace.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "OPENAI_API_KEY": "",
            "WORKSPACE_ROOT": str(workspace),
            "CHROMA_PATH": str(test_root / "chroma_data"),
            "LOCALAPPDATA": str(test_root / "localappdata"),
        }
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(executable)],
        cwd=str(executable.parent),
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(f"Packaged EXE exited before health check with code {process.returncode}.")
        status, body = _get("/health")
        if status == 200:
            yield {"process": process, "workspace": workspace, "health": body}
            break
        time.sleep(0.5)
    else:
        pytest.fail("Packaged EXE did not expose /health within 60 seconds.")

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def test_packaged_exe_health(packaged_app):
    assert '"status":"ok"' in packaged_app["health"].replace(" ", "")


def test_packaged_exe_serves_bundled_frontend(packaged_app):
    status, html = _get("/")
    assert status == 200
    assert "Coding Machine" in html

    css_status, css = _get("/css/styles.css")
    js_status, javascript = _get("/js/main.js")
    assert css_status == 200 and "--bg-editor" in css
    assert js_status == 200 and "cmApp" in javascript


def test_packaged_exe_api_is_available_without_openai_key(packaged_app):
    status, body = _get("/api/skills")
    assert status == 200
    assert '"skills"' in body
    assert "OPENAI_API_KEY" not in body


def test_packaged_exe_rejects_encoded_path_traversal(packaged_app):
    status, body = _get("/%2e%2e/%2e%2e/backend/.env")
    assert status in {400, 404}
    assert "OPENAI_API_KEY=" not in body
