"""Workspace indexing for local ChromaDB codebase search."""

from __future__ import annotations

import hashlib
import os
import re
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ..config import WORKSPACE_PATH
from ..memory.vector_store import vector_store
from .chunker import chunk_text


IGNORED_DIRECTORIES = {".git", ".pytest_cache", "node_modules", "__pycache__", "chroma_data", "sessions"}
_SEARCH_STOP_WORDS = {"the", "and", "for", "with", "from", "that", "this", "how", "what", "where", "does"}


class WorkspaceIndexer:
    def __init__(self, workspace_root: str | Path = WORKSPACE_PATH, store: Any = vector_store) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.store = store
        self._fingerprints: dict[str, tuple[int, int]] = {}
        self._lock = threading.RLock()

    def _resolve_path(self, file_path: str | Path) -> Path:
        candidate = Path(file_path)
        path = candidate.resolve() if candidate.is_absolute() else (self.workspace_root / candidate).resolve()
        if not path.is_relative_to(self.workspace_root):
            raise PermissionError("Path outside workspace")
        return path

    def index_file(self, file_path: str | Path, force: bool = False) -> dict[str, Any]:
        path = self._resolve_path(file_path)
        if not path.is_file():
            return {"success": False, "error": f"File not found: {file_path}"}
        relative_path = path.relative_to(self.workspace_root).as_posix()
        stat = path.stat()
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        if not force and self._fingerprints.get(relative_path) == fingerprint:
            return {"success": True, "file_path": relative_path, "chunks": 0, "skipped": True}
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self.store.replace_code_file(relative_path, [])
            self._fingerprints[relative_path] = fingerprint
            return {
                "success": True,
                "file_path": relative_path,
                "chunks": 0,
                "skipped": True,
                "reason": "File is not UTF-8 text",
            }
        except OSError as exc:
            self.store.replace_code_file(relative_path, [])
            return {"success": False, "file_path": relative_path, "error": str(exc)}

        chunks = chunk_text(text, relative_path)
        for index, chunk in enumerate(chunks):
            identity = f"{relative_path}:{index}:{chunk['text']}"
            chunk["id"] = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        result = self.store.replace_code_file(relative_path, chunks)
        self._fingerprints[relative_path] = fingerprint
        return result

    def index_workspace(
        self,
        file_types: Iterable[str] | None = None,
        incremental: bool = True,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        normalized_types = self._normalize_file_types(file_types)
        indexed = 0
        skipped = 0
        errors = []
        candidates: list[Path] = []
        for root, directories, files in os.walk(self.workspace_root):
            directories[:] = [name for name in directories if name not in IGNORED_DIRECTORIES]
            candidates.extend(
                Path(root) / filename
                for filename in files
                if not normalized_types or Path(filename).suffix.lower() in normalized_types
            )
        with self._lock:
            total = len(candidates)
            for current, path in enumerate(candidates, 1):
                try:
                    result = self.index_file(path, force=not incremental)
                    if result.get("success") and not result.get("skipped"):
                        indexed += 1
                    else:
                        skipped += 1
                    if result.get("error"):
                        errors.append(result["error"])
                except Exception as exc:
                    skipped += 1
                    errors.append(f"{path}: {exc}")
                if progress_callback:
                    progress_callback({
                        "current": current,
                        "total": total,
                        "path": path.relative_to(self.workspace_root).as_posix(),
                        "indexed": indexed,
                        "skipped": skipped,
                        "errors": len(errors),
                    })
        return {
            "success": not errors,
            "indexed": indexed,
            "skipped": skipped,
            "errors": errors,
            "total": len(candidates),
            "file_types": sorted(normalized_types),
            "incremental": incremental,
        }

    def search_codebase(self, query: str, file_types: Iterable[str] | None = None) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            return {"success": False, "error": "Search query is required", "results": []}
        try:
            if self.store.codebase.count() == 0:
                self.index_workspace()
        except (AttributeError, OSError, RuntimeError):
            pass
        normalized_types = self._normalize_file_types(file_types)
        where = {"extension": {"$in": sorted(normalized_types)}} if normalized_types else None
        semantic = self.store.search_codebase(query, limit=10, where=where) if where else self.store.search_codebase(query, limit=10)
        exact = self._exact_search(query, normalized_types, limit=10)
        return self._merge_results(query, semantic, exact, limit=5)

    def _exact_search(self, query: str, file_types: set[str], limit: int = 10) -> list[dict[str, Any]]:
        terms = {term for term in re.findall(r"[A-Za-z0-9_]{3,}", query.casefold()) if term not in _SEARCH_STOP_WORDS}
        if not terms:
            terms = {query.casefold().strip()}
        candidates: list[dict[str, Any]] = []
        for root, directories, files in os.walk(self.workspace_root):
            directories[:] = [name for name in directories if name not in IGNORED_DIRECTORIES]
            for filename in files:
                path = Path(root) / filename
                if file_types and path.suffix.lower() not in file_types:
                    continue
                try:
                    if path.stat().st_size > 1_000_000:
                        continue
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                relative_path = path.relative_to(self.workspace_root).as_posix()
                folded_path = relative_path.casefold()
                path_score = sum(folded_path.count(term) for term in terms)
                path_match = query.casefold() in folded_path
                if path_match:
                    path_score += 10
                for index, chunk in enumerate(chunk_text(text, relative_path)):
                    content = chunk["text"]
                    folded = content.casefold()
                    score = path_score + sum(folded.count(term) for term in terms)
                    if query.casefold() in folded:
                        score += 3
                    if score:
                        candidates.append(
                            {
                                "id": f"exact:{relative_path}:{index}",
                                "text": content,
                                "metadata": chunk["metadata"],
                                "distance": None,
                                "exact_score": score,
                                "path_match": path_match,
                                "match_type": "exact",
                            }
                        )
        return sorted(candidates, key=lambda item: item["exact_score"], reverse=True)[:limit]

    @staticmethod
    def _merge_results(
        query: str,
        semantic: dict[str, Any],
        exact: list[dict[str, Any]],
        limit: int = 5,
    ) -> dict[str, Any]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for rank, result in enumerate(semantic.get("results", []) if isinstance(semantic, dict) else []):
            item = dict(result)
            item["match_type"] = "semantic"
            key = (str(item.get("metadata", {}).get("file_path", "")), str(item.get("text", "")))
            item["hybrid_score"] = 0.6 / (rank + 1)
            merged[key] = item
        for rank, result in enumerate(exact):
            item = dict(result)
            key = (str(item.get("metadata", {}).get("file_path", "")), str(item.get("text", "")))
            if key in merged:
                merged[key]["match_type"] = "hybrid"
                merged[key]["hybrid_score"] += 0.4 / (rank + 1) + min(float(item.get("exact_score", 0)), 10) / 25
            else:
                item["hybrid_score"] = 0.4 / (rank + 1) + min(float(item.get("exact_score", 0)), 10) / 25
                merged[key] = item
            if item.get("path_match"):
                merged[key]["hybrid_score"] += 1.0
        results = sorted(merged.values(), key=lambda item: item.get("hybrid_score", 0), reverse=True)[:limit]
        return {
            "success": bool(semantic.get("success")) or bool(exact),
            "query": query,
            "retrieval": "hybrid",
            "results": results,
            "semantic_error": semantic.get("error") if isinstance(semantic, dict) else None,
        }

    @staticmethod
    def _normalize_file_types(file_types: Iterable[str] | None) -> set[str]:
        values = {str(item).strip().lower() for item in file_types or [] if str(item).strip()}
        if values.intersection({"*", "all", "all_extensions"}):
            return set()
        return {
            value if value.startswith(".") else f".{value}"
            for value in values
            if value
        }


workspace_indexer = WorkspaceIndexer()
