from __future__ import annotations

from pathlib import Path


def test_database_form_uses_backend_field_names():
    source = Path("frontend/js/main.js").read_text(encoding="utf-8")

    assert 'connection_id: this.dbForm.connectionId' in source
    assert 'db_type: this.dbForm.dbType' in source
    assert 'connection_string: this.dbForm.connectionString' in source
