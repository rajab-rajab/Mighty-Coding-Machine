"""Windows-user-bound storage for sensitive Coding Machine credentials."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import threading
from pathlib import Path
from typing import Any


class CredentialStore:
    """Encrypt credentials with Windows DPAPI and never write plaintext values."""

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        config_root = Path(os.getenv("LOCALAPPDATA", Path.home() / ".coding-machine")) / "CodingMachine"
        self.path = Path(path or config_root / "credentials.dat")
        self._lock = threading.RLock()

    @property
    def available(self) -> bool:
        return os.name == "nt"

    def set(self, name: str, value: str) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            return {"success": False, "error": "Credential name is required."}
        if not isinstance(value, str) or not value:
            return {"success": False, "error": "Credential value is required."}
        if not self.available:
            return {"success": False, "error": "Windows DPAPI is unavailable on this platform."}
        try:
            with self._lock:
                values = self._read_values()
                values[name.strip()] = base64.b64encode(self._protect(value.encode("utf-8"))).decode("ascii")
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix(".tmp")
                temporary.write_text(json.dumps({"version": 1, "values": values}), encoding="utf-8")
                temporary.replace(self.path)
            return {"success": True, "name": name.strip()}
        except (OSError, ValueError, TypeError) as exc:
            return {"success": False, "error": str(exc)}

    def get(self, name: str) -> str | None:
        if not self.available:
            return None
        try:
            with self._lock:
                encoded = self._read_values().get(name)
                if not encoded:
                    return None
                return self._unprotect(base64.b64decode(encoded)).decode("utf-8")
        except (OSError, ValueError, TypeError, UnicodeDecodeError):
            return None

    def delete(self, name: str) -> dict[str, Any]:
        try:
            with self._lock:
                values = self._read_values()
                values.pop(name, None)
                if values:
                    self.path.write_text(json.dumps({"version": 1, "values": values}), encoding="utf-8")
                elif self.path.exists():
                    self.path.unlink()
            return {"success": True, "name": name}
        except OSError as exc:
            return {"success": False, "error": str(exc)}

    def status(self, name: str) -> dict[str, Any]:
        return {
            "success": True,
            "available": self.available,
            "configured": self.get(name) is not None,
            "backend": "windows-dpapi" if self.available else "unavailable",
        }

    def _read_values(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        values = payload.get("values", {})
        if not isinstance(values, dict):
            raise ValueError("Invalid credential store format")
        return {str(key): str(value) for key, value in values.items()}

    @staticmethod
    def _protect(value: bytes) -> bytes:
        if os.name != "nt":
            raise RuntimeError("Windows DPAPI is unavailable on this platform")
        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        crypt32 = ctypes.WinDLL("Crypt32.dll")
        kernel32 = ctypes.WinDLL("Kernel32.dll")
        source = ctypes.create_string_buffer(value)
        source_blob = DataBlob(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
        result_blob = DataBlob()
        if not crypt32.CryptProtectData(ctypes.byref(source_blob), "Coding Machine", None, None, None, 0, ctypes.byref(result_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(result_blob.pbData, result_blob.cbData)
        finally:
            kernel32.LocalFree(result_blob.pbData)

    @staticmethod
    def _unprotect(value: bytes) -> bytes:
        if os.name != "nt":
            raise RuntimeError("Windows DPAPI is unavailable on this platform")
        class DataBlob(ctypes.Structure):
            _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

        crypt32 = ctypes.WinDLL("Crypt32.dll")
        kernel32 = ctypes.WinDLL("Kernel32.dll")
        source = ctypes.create_string_buffer(value)
        source_blob = DataBlob(len(value), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
        result_blob = DataBlob()
        if not crypt32.CryptUnprotectData(ctypes.byref(source_blob), None, None, None, None, 0, ctypes.byref(result_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(result_blob.pbData, result_blob.cbData)
        finally:
            kernel32.LocalFree(result_blob.pbData)


credential_store = CredentialStore()

