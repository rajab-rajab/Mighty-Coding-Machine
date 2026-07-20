from __future__ import annotations

from backend.agents.structured_output import StructuredOutputError, parse_tool_arguments
from backend.credentials import CredentialStore


def test_structured_tool_arguments_enforce_required_types_and_enums():
    schema = {
        "type": "function",
        "function": {
            "name": "example",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["safe"]}},
                "required": ["mode"],
                "additionalProperties": False,
            },
        },
    }
    assert parse_tool_arguments("example", '{"mode":"safe"}', [schema]) == {"mode": "safe"}
    for arguments in ('{}', '{"mode": "unsafe"}', '{"mode": 1}', '{"mode":"safe","extra":true}'):
        try:
            parse_tool_arguments("example", arguments, [schema])
        except StructuredOutputError:
            continue
        raise AssertionError(f"Expected structured validation to reject {arguments}")


def test_credential_store_does_not_write_plaintext_values(tmp_path, monkeypatch):
    store = CredentialStore(tmp_path / "credentials.dat")
    monkeypatch.setattr(type(store), "available", property(lambda self: True))
    monkeypatch.setattr(store, "_protect", lambda value: b"encrypted:" + value)
    monkeypatch.setattr(store, "_unprotect", lambda value: value.removeprefix(b"encrypted:"))

    result = store.set("openai_api_key", "sk-secret-value")
    assert result["success"] is True
    assert store.get("openai_api_key") == "sk-secret-value"
    assert "sk-secret-value" not in (tmp_path / "credentials.dat").read_text(encoding="utf-8")
    assert store.status("openai_api_key")["configured"] is True

