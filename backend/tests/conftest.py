"""Shared pytest fixtures for backend tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def app():
    from backend.server import create_app

    return create_app()


@pytest.fixture
def socketio_client(app):
    from backend.server import socketio

    client = socketio.test_client(app)
    yield client
    if client.is_connected():
        client.disconnect()


@pytest.fixture
def mock_workspace(tmp_path, mocker):
    from backend.tools import file_ops

    mocker.patch.object(file_ops, "WORKSPACE_PATH", tmp_path)
    return tmp_path


@pytest.fixture
def mock_openai(mocker):
    return mocker.patch("backend.agents.engine.OpenAI")

