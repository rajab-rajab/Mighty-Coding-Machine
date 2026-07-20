"""Cross-platform single-instance lock for the Coding Machine desktop app."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import TextIO


class SingleInstanceLock:
    """Hold an operating-system file lock shared by source and packaged runs."""

    def __init__(self, name: str = "coding-machine.lock") -> None:
        base = Path(os.getenv("LOCALAPPDATA", Path.home() / ".coding-machine")) / "CodingMachine"
        self.path = base / name
        self.handle: TextIO | None = None
        self.mutex_handle: int | None = None
        self.acquired = False

    def acquire(self) -> bool:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            mutex_name = f"Local\\CodingMachine.{self.path.stem}"
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            if not handle:
                return False
            if ctypes.get_last_error() == 183:
                kernel32.CloseHandle(handle)
                return False
            self.mutex_handle = handle
            self.acquired = True
            return True

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.path = Path(tempfile.gettempdir()) / "CodingMachine" / self.path.name
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("a+", encoding="utf-8")
        except OSError:
            self.handle = None
            return False
        try:
            self.handle.seek(0)
            self.handle.write("Coding Machine\n")
            self.handle.flush()
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError):
            try:
                self.handle.close()
            except OSError:
                pass
            self.handle = None
            return False
        self.acquired = True
        return True

    def release(self) -> None:
        if self.mutex_handle:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(self.mutex_handle)
            self.mutex_handle = None
            self.acquired = False
            return
        if not self.handle:
            return
        try:
            if self.acquired:
                if sys.platform == "win32":
                    import msvcrt

                    self.handle.seek(0)
                    msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.acquired = False
            self.handle.close()
            self.handle = None
