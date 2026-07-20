"""Prompt-cache configuration and stable-prefix key generation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..config import MODEL, PROMPT_CACHE_ENABLED


def build_prompt_cache_key(
    system_prompt: str,
    tools: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    model: str = MODEL,
    scope: str = "agent",
) -> str:
    """Build a deterministic key for one stable CM prompt/tool prefix.

    User messages, RAG results, task state, and tool results are intentionally
    excluded so changing request data does not create a new cache bucket.
    """
    payload = {
        "scope": scope,
        "model": model,
        "system_prompt": str(system_prompt),
        "tools": tools,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
    return f"cm-{scope}-{digest}"


def prompt_cache_arguments(cache_key: str | None) -> dict[str, Any]:
    """Return SDK arguments without disabling older/fake clients."""
    if not PROMPT_CACHE_ENABLED or not cache_key:
        return {}
    return {"prompt_cache_key": cache_key}

