"""Small, dependency-free text chunking helpers for codebase search."""

from __future__ import annotations

from pathlib import PurePosixPath


def chunk_text(
    text: str,
    file_path: str = "",
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[dict]:
    """Split text into overlapping character chunks with line metadata."""
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("chunk_size must be positive and overlap must be smaller than chunk_size")
    if not text:
        return []

    step = chunk_size - overlap
    chunks = []
    for start in range(0, len(text), step):
        end = min(start + chunk_size, len(text))
        chunks.append(
            {
                "text": text[start:end],
                "metadata": {
                    "file_path": file_path,
                    "extension": PurePosixPath(file_path).suffix.lower(),
                    "start_line": text.count("\n", 0, start) + 1,
                    "end_line": text.count("\n", 0, end) + 1,
                },
            }
        )
        if end >= len(text):
            break
    return chunks
