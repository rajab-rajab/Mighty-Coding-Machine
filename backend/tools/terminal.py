"""Windows-compatible interactive terminal sessions using subprocess pipes."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any, TextIO

from ..config import WORKSPACE_PATH


class TerminalSession:
    """Own one interactive cmd.exe process and stream both output pipes."""

    def __init__(self, session_id: str, socketio: Any, client_sid: str | None = None) -> None:
        self.session_id = session_id
        self.socketio = socketio
        self.client_sid = client_sid
        self._write_lock = threading.Lock()
        self._closed = threading.Event()
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            ["cmd.exe"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=True,
            cwd=WORKSPACE_PATH,
            bufsize=1,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        self._start_reader(self.process.stdout, "stdout")
        self._start_reader(self.process.stderr, "stderr")

    def _start_reader(self, stream: TextIO | None, stream_type: str) -> None:
        if stream is None:
            return
        threading.Thread(
            target=self._read_stream,
            args=(stream, stream_type),
            name=f"cm-terminal-{self.session_id}-{stream_type}",
            daemon=True,
        ).start()

    def _read_stream(self, stream: TextIO, stream_type: str) -> None:
        try:
            while True:
                chunk = stream.read(1)
                if chunk == "":
                    break
                payload = {
                    "session_id": self.session_id,
                    "type": stream_type,
                    "data": chunk,
                }
                emit_kwargs = {"to": self.client_sid} if self.client_sid else {}
                self.socketio.emit(
                    "terminal_output",
                    payload,
                    **emit_kwargs,
                )
        finally:
            stream.close()

    def write(self, command: str) -> dict[str, Any]:
        """Write one command to stdin and flush it immediately."""
        if self._closed.is_set() or self.process.poll() is not None:
            return {"success": False, "error": "Terminal session is closed", "session_id": self.session_id}
        if not isinstance(command, str):
            return {"success": False, "error": "Terminal command must be text", "session_id": self.session_id}

        try:
            with self._write_lock:
                if self.process.stdin is None:
                    raise RuntimeError("Terminal stdin is unavailable")
                self.process.stdin.write(command + "\n")
                self.process.stdin.flush()
            return {"success": True, "session_id": self.session_id}
        except (OSError, ValueError, RuntimeError) as exc:
            return {"success": False, "error": str(exc), "session_id": self.session_id}

    def close(self) -> dict[str, Any]:
        """Close the shell without blocking the Socket.IO worker."""
        if self._closed.is_set():
            return {"success": True, "session_id": self.session_id}
        self._closed.set()
        try:
            if self.process.poll() is None and self.process.stdin is not None:
                with self._write_lock:
                    self.process.stdin.write("exit\n")
                    self.process.stdin.flush()
            self.process.wait(timeout=2)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                self.process.kill()
        finally:
            if self.process.stdin is not None:
                self.process.stdin.close()
        return {"success": True, "session_id": self.session_id}

    @property
    def is_running(self) -> bool:
        return not self._closed.is_set() and self.process.poll() is None
