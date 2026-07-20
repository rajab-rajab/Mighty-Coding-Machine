"""Persistent ChromaDB collections using Chroma's offline default embeddings."""

from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

from ..config import WORKSPACE_PATH

DEFAULT_CHROMA_PATH = os.getenv("CHROMA_PATH", str(WORKSPACE_PATH / "chroma_data"))


class VectorStore:
    """Own persistent memory and codebase collections with local embeddings."""

    def __init__(self, path: str | Path = DEFAULT_CHROMA_PATH) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self.client = chromadb.PersistentClient(path=self.path)
        self.embedding_function = DefaultEmbeddingFunction()
        self.memory = self.client.get_or_create_collection(
            name="memory",
            embedding_function=self.embedding_function,
        )
        self.codebase = self.client.get_or_create_collection(
            name="codebase",
            embedding_function=self.embedding_function,
        )

    def add_memory(self, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not text.strip():
            return {"success": False, "error": "Memory text is required"}
        memory_id = str(uuid.uuid4())
        clean_metadata = {key: self._metadata_value(value) for key, value in (metadata or {}).items()}
        with self._lock:
            self.memory.add(ids=[memory_id], documents=[text], metadatas=[clean_metadata or {"source": "user"}])
        return {"success": True, "id": memory_id}

    def search_memory(self, query: str, limit: int = 3) -> dict[str, Any]:
        return self._search(self.memory, query, min(max(limit, 1), 3))

    def replace_code_file(self, file_path: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            self.codebase.delete(where={"file_path": file_path})
            if chunks:
                self.codebase.upsert(
                    ids=[chunk["id"] for chunk in chunks],
                    documents=[chunk["text"] for chunk in chunks],
                    metadatas=[
                        {key: self._metadata_value(value) for key, value in chunk["metadata"].items()}
                        for chunk in chunks
                    ],
                )
        return {"success": True, "file_path": file_path, "chunks": len(chunks)}

    def search_codebase(
        self,
        query: str,
        limit: int = 5,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._search(self.codebase, query, min(max(limit, 1), 5), where=where)

    @staticmethod
    def _search(
        collection: Any,
        query: str,
        limit: int,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not query.strip():
            return {"success": False, "error": "Search query is required", "results": []}
        try:
            query_args = {"query_texts": [query], "n_results": limit}
            if where:
                query_args["where"] = where
            result = collection.query(**query_args)
            documents = (result.get("documents") or [[]])[0]
            metadatas = (result.get("metadatas") or [[]])[0]
            distances = (result.get("distances") or [[]])[0]
            ids = (result.get("ids") or [[]])[0]
            results = [
                {
                    "id": ids[index] if index < len(ids) else "",
                    "text": document,
                    "metadata": metadatas[index] if index < len(metadatas) else {},
                    "distance": distances[index] if index < len(distances) else None,
                }
                for index, document in enumerate(documents)
            ]
            return {"success": True, "results": results}
        except Exception as exc:
            return {"success": False, "error": str(exc), "results": []}

    @staticmethod
    def _metadata_value(value: Any) -> str | int | float | bool:
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)


vector_store = VectorStore()
