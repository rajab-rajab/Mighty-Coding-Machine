"""Debounced filesystem watcher for incremental codebase indexing."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from watchdog.events import FileCreatedEvent, FileModifiedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .indexer import IGNORED_DIRECTORIES, WorkspaceIndexer, workspace_indexer


class WorkspaceEventHandler(FileSystemEventHandler):
    def __init__(self, watcher: "WorkspaceWatcher") -> None:
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if not event.is_directory:
            self.watcher.schedule_reindex(event.src_path)

    def on_modified(self, event: FileModifiedEvent) -> None:
        if not event.is_directory:
            self.watcher.schedule_reindex(event.src_path)


class WorkspaceWatcher:
    def __init__(self, indexer: WorkspaceIndexer = workspace_indexer, debounce_seconds: float = 3.0) -> None:
        self.indexer = indexer
        self.debounce_seconds = debounce_seconds
        self.observer: Observer | None = None
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.RLock()

    def start(self) -> None:
        if self.observer is not None:
            return
        self.observer = Observer()
        self.observer.schedule(
            WorkspaceEventHandler(self), str(self.indexer.workspace_root), recursive=True
        )
        self.observer.start()

    def stop(self) -> None:
        with self._lock:
            timers = list(self._timers.values())
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        if self.observer is not None:
            self.observer.stop()
            self.observer.join(timeout=5)
            self.observer = None

    def schedule_reindex(self, file_path: str) -> None:
        path = Path(file_path).resolve()
        if not self._is_indexable(path):
            return
        key = str(path)
        with self._lock:
            previous = self._timers.pop(key, None)
            if previous is not None:
                previous.cancel()
            timer = threading.Timer(self.debounce_seconds, self._reindex, args=(path, key))
            timer.daemon = True
            self._timers[key] = timer
            timer.start()

    def _reindex(self, path: Path, key: str) -> None:
        try:
            if path.is_file():
                relative_path = path.relative_to(self.indexer.workspace_root).as_posix()
                self.indexer.index_file(relative_path)
        finally:
            with self._lock:
                self._timers.pop(key, None)

    def _is_indexable(self, path: Path) -> bool:
        try:
            relative_parts = path.relative_to(self.indexer.workspace_root).parts
        except ValueError:
            return False
        return not any(part in IGNORED_DIRECTORIES for part in relative_parts)

