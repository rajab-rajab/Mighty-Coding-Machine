"""Small, dependency-free validation layer for model-generated tool arguments."""

from __future__ import annotations

import json
from typing import Any, Iterable


class StructuredOutputError(ValueError):
    """Raised when a model tool call does not match its declared contract."""


def parse_tool_arguments(
    tool_name: str,
    raw_arguments: str,
    tool_schemas: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Parse and validate a JSON tool payload against its OpenAI schema.

    This intentionally validates the schema subset used by CM tools and
    returns a normalized dictionary so callers never execute unvalidated data.
    """
    try:
        payload = json.loads(raw_arguments or "{}")
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"Invalid JSON arguments for {tool_name}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise StructuredOutputError(f"Arguments for {tool_name} must be a JSON object")

    schema = next(
        (
            item.get("function", {})
            for item in tool_schemas
            if isinstance(item, dict) and item.get("function", {}).get("name") == tool_name
        ),
        None,
    )
    if schema is None:
        return payload

    parameters = schema.get("parameters", {})
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])
    missing = [name for name in required if name not in payload]
    if missing:
        raise StructuredOutputError(f"Missing required arguments for {tool_name}: {', '.join(missing)}")
    if parameters.get("additionalProperties") is False:
        unknown = sorted(set(payload) - set(properties))
        if unknown:
            raise StructuredOutputError(f"Unknown arguments for {tool_name}: {', '.join(unknown)}")

    for name, value in payload.items():
        definition = properties.get(name, {})
        _validate_value(tool_name, name, value, definition)
    return payload


def _validate_value(tool_name: str, name: str, value: Any, definition: dict[str, Any]) -> None:
    expected = definition.get("type")
    valid = {
        "string": isinstance(value, str),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
        "boolean": isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
    }
    if expected in valid and not valid[expected]:
        raise StructuredOutputError(f"Argument {name} for {tool_name} must be {expected}")
    choices = definition.get("enum")
    if choices and value not in choices:
        raise StructuredOutputError(f"Argument {name} for {tool_name} has an unsupported value")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in definition and value < definition["minimum"]:
            raise StructuredOutputError(f"Argument {name} for {tool_name} is below the minimum")
        if "maximum" in definition and value > definition["maximum"]:
            raise StructuredOutputError(f"Argument {name} for {tool_name} exceeds the maximum")

