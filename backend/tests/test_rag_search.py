from __future__ import annotations

from backend.rag.indexer import WorkspaceIndexer


class EmptyCollection:
    def count(self):
        return 0


class SearchStore:
    def __init__(self):
        self.codebase = EmptyCollection()
        self.indexed = False

    def replace_code_file(self, file_path, chunks):
        return {"success": True, "file_path": file_path, "chunks": len(chunks)}

    def search_codebase(self, query, limit=5):
        return {"success": self.indexed, "results": [{"text": query}] if self.indexed else []}


def test_search_indexes_an_empty_collection(tmp_path, monkeypatch):
    store = SearchStore()
    indexer = WorkspaceIndexer(tmp_path, store)
    (tmp_path / "main.py").write_text("print('hello')", encoding="utf-8")

    def fake_index_workspace():
        store.indexed = True
        return {"success": True, "indexed": 1, "skipped": 0, "errors": []}

    monkeypatch.setattr(indexer, "index_workspace", fake_index_workspace)
    result = indexer.search_codebase("hello")
    assert result["success"] is True
    assert result["results"][0]["text"] == "hello"
    assert result["retrieval"] == "hybrid"


def test_hybrid_search_can_return_exact_matches(tmp_path):
    store = SearchStore()
    store.indexed = True
    indexer = WorkspaceIndexer(tmp_path, store)
    (tmp_path / "service.py").write_text("def create_invoice():\n    return True\n", encoding="utf-8")

    result = indexer.search_codebase("create_invoice")

    assert result["success"] is True
    assert any(item["match_type"] == "exact" for item in result["results"])


def test_hybrid_search_matches_nested_file_paths(tmp_path):
    store = SearchStore()
    store.indexed = True
    indexer = WorkspaceIndexer(tmp_path, store)
    target = tmp_path / "billing" / "invoice_service.py"
    target.parent.mkdir()
    target.write_text("def create_invoice():\n    return True\n", encoding="utf-8")

    result = indexer.search_codebase("billing/invoice_service.py")

    assert result["success"] is True
    assert result["results"][0]["metadata"]["file_path"] == "billing/invoice_service.py"


def test_index_workspace_skips_non_utf8_files_without_error(tmp_path):
    store = SearchStore()
    indexer = WorkspaceIndexer(tmp_path, store)
    (tmp_path / "agent_metrics.db").write_bytes(b"SQLite format 3\x00\x8a")

    result = indexer.index_workspace()

    assert result["success"] is True
    assert result["errors"] == []
    assert result["skipped"] == 1


def test_index_workspace_includes_txt_files_without_filter(tmp_path):
    store = SearchStore()
    indexer = WorkspaceIndexer(tmp_path, store)
    (tmp_path / "notes.txt").write_text("customer total notes", encoding="utf-8")

    result = indexer.index_workspace()

    assert result["success"] is True
    assert result["indexed"] == 1
