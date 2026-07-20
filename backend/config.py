"""Application configuration loaded from the backend environment file."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .credentials import credential_store


if getattr(sys, "frozen", False):
    APPLICATION_PATH = Path(sys._MEIPASS).resolve()
else:
    APPLICATION_PATH = Path(__file__).resolve().parent.parent

BACKEND_DIR = APPLICATION_PATH / "backend"
PROJECT_DIR = APPLICATION_PATH
ENV_FILE = BACKEND_DIR / ".env"
EXPLICIT_WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT")
USER_CONFIG_DIR = Path(os.getenv("LOCALAPPDATA", Path.home() / ".coding-machine")) / "CodingMachine"
WORKSPACE_OVERRIDE_FILE = USER_CONFIG_DIR / "workspace-root.txt"

load_dotenv(ENV_FILE)

SECURE_CREDENTIALS_ENABLED = os.getenv("CM_SECURE_CREDENTIALS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}
ENV_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
SECURE_OPENAI_API_KEY = credential_store.get("openai_api_key") if SECURE_CREDENTIALS_ENABLED else None
OPENAI_API_KEY = SECURE_OPENAI_API_KEY or ENV_OPENAI_API_KEY
OPENAI_API_KEY_SOURCE = "secure_store" if SECURE_OPENAI_API_KEY else ("environment" if ENV_OPENAI_API_KEY else "missing")
MODEL = os.getenv("MODEL", "gpt-4o")
PROMPT_CACHE_ENABLED = os.getenv("CM_PROMPT_CACHE_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


def _default_workspace_root() -> Path:
    if not getattr(sys, "frozen", False):
        return PROJECT_DIR / "workspace"

    executable = Path(sys.executable).resolve()
    candidates = [executable.parent / "workspace", Path.cwd() / "workspace"]
    if len(executable.parents) > 2:
        candidates.append(executable.parents[2] / "workspace")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return Path(os.path.expanduser("~/CodingMachineWorkspace"))


def _saved_workspace_root() -> str:
    try:
        return WORKSPACE_OVERRIDE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_workspace_root(path: str | os.PathLike[str]) -> str:
    selected = Path(path).expanduser().resolve()
    selected.mkdir(parents=True, exist_ok=True)
    WORKSPACE_OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = WORKSPACE_OVERRIDE_FILE.with_suffix(".tmp")
    temporary.write_text(str(selected), encoding="utf-8")
    temporary.replace(WORKSPACE_OVERRIDE_FILE)
    return str(selected)


WORKSPACE_ROOT = EXPLICIT_WORKSPACE_ROOT or _saved_workspace_root() or os.getenv("WORKSPACE_ROOT") or str(_default_workspace_root())

_workspace_root = Path(WORKSPACE_ROOT).expanduser()
WORKSPACE_PATH = (_workspace_root if _workspace_root.is_absolute() else PROJECT_DIR / _workspace_root).resolve()


class Config:
    """Attribute-based configuration facade for the desktop bridge."""

    OPENAI_API_KEY = OPENAI_API_KEY
    MODEL = MODEL
    PROMPT_CACHE_ENABLED = PROMPT_CACHE_ENABLED
    OPENAI_API_KEY_SOURCE = OPENAI_API_KEY_SOURCE
    SECURE_CREDENTIALS_ENABLED = SECURE_CREDENTIALS_ENABLED
    WORKSPACE_ROOT = str(WORKSPACE_PATH)
    APPLICATION_PATH = str(APPLICATION_PATH)
