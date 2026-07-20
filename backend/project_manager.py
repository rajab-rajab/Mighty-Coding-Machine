"""Workspace project allocation for generated applications."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import WORKSPACE_PATH


@dataclass(frozen=True)
class ProjectInfo:
    """A newly allocated, workspace-relative project."""

    name: str
    relative_path: str
    absolute_path: Path
    main_file: str


_GENERATION_WORDS = re.compile(r"\b(create|build|make|write|generate|scaffold|implement|develop)\b", re.I)
_LEADING_WORDS = re.compile(r"^(?:please\s+)?(?:create|build|make|write|generate|scaffold|implement|develop)\s+", re.I)
_ARTICLE_WORDS = re.compile(r"^(?:a|an|the)\s+", re.I)


def is_generation_request(prompt: str) -> bool:
    """Return whether a request is asking CM to create or modify an application."""
    return bool(isinstance(prompt, str) and _GENERATION_WORDS.search(prompt))


def derive_project_name(prompt: str, requested_name: str | None = None) -> str:
    """Derive a readable safe project directory name from the user request."""
    source = (requested_name or "").strip()
    if not source:
        source = next((line.strip() for line in prompt.splitlines() if line.strip()), "Project")
        source = _LEADING_WORDS.sub("", source)
        source = _ARTICLE_WORDS.sub("", source)
    words = re.findall(r"[A-Za-z0-9]+", source)
    name = "_".join(words[:8]) or "Project"
    return name[:80]


def create_project(prompt: str, requested_name: str | None = None) -> ProjectInfo:
    """Create a unique project directory without replacing an existing project."""
    WORKSPACE_PATH.mkdir(parents=True, exist_ok=True)
    base_name = derive_project_name(prompt, requested_name)
    candidate = base_name
    suffix = 1
    while True:
        project_path = WORKSPACE_PATH / candidate
        try:
            project_path.mkdir()
            break
        except FileExistsError:
            suffix += 1
            candidate = f"{base_name}_{suffix}"
    relative_path = project_path.relative_to(WORKSPACE_PATH).as_posix()
    return ProjectInfo(candidate, relative_path, project_path, f"{relative_path}/main.py")
