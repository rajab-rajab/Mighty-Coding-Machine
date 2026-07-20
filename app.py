"""PyWebView entry point for Mighty Coding Machine (MCM)."""

from __future__ import annotations

import os
import json
import re
import shutil
import sys
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import webview
import pystray
from PIL import Image

from backend.config import Config, save_workspace_root
from backend.credentials import credential_store
from backend.instance_lock import SingleInstanceLock
from backend.memory.metadata_store import metadata_store
from backend.server import start_server, start_workspace_indexing
from backend.tools.file_ops import resolve_workspace_path
from backend.rag.indexer import workspace_indexer
from backend.rag.watcher import WorkspaceWatcher


SERVER_STARTUP_DELAY_SECONDS = 1.0
TRAY_SAVE_TIMEOUT_SECONDS = 3.0
TRAY_SAVE_POLL_INTERVAL_SECONDS = 0.05

if getattr(sys, "frozen", False):
    APPLICATION_PATH = sys._MEIPASS
else:
    APPLICATION_PATH = os.path.dirname(os.path.abspath(__file__))


def _shutdown_window_gracefully(
    timeout_seconds: float = TRAY_SAVE_TIMEOUT_SECONDS,
    poll_interval_seconds: float = TRAY_SAVE_POLL_INTERVAL_SECONDS,
) -> bool:
    """Save the current session through the webview before closing its window."""
    windows = list(getattr(webview, "windows", []) or [])
    if not windows:
        return False

    window = windows[0]
    saved = False
    try:
        window.evaluate_js(
            """
            (async () => {
              window.__mcmTrayShutdownReady = false;
              try {
                if (typeof window.cmSaveSessionBeforeExit === "function") {
                  await window.cmSaveSessionBeforeExit();
                }
              } finally {
                window.__mcmTrayShutdownReady = true;
              }
            })();
            """
        )
        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while time.monotonic() < deadline:
            result = window.evaluate_js("Boolean(window.__mcmTrayShutdownReady)")
            if result is True or str(result).strip().lower() == "true":
                saved = True
                break
            time.sleep(max(0.0, poll_interval_seconds))
    except Exception:
        saved = False
    finally:
        window.destroy()
    return saved


def create_tray_icon() -> pystray.Icon:
    """Create the Windows tray icon on its own daemon thread."""
    image = Image.new("RGB", (64, 64), color="black")

    def on_quit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        icon.stop()
        threading.Thread(
            target=_shutdown_window_gracefully,
            name="mcm-graceful-shutdown",
            daemon=True,
        ).start()

    menu = pystray.Menu(pystray.MenuItem("Quit Mighty Coding Machine", on_quit))
    icon = pystray.Icon("mighty_coding_machine", image, "Mighty Coding Machine (MCM)", menu)
    threading.Thread(target=icon.run, name="cm-system-tray", daemon=True).start()
    return icon


class Api:
    """Secure JavaScript bridge for workspace file operations."""

    def _secure_path(self, relative_path: str) -> str:
        """Resolve a path while preventing traversal and symlink escapes."""
        try:
            return str(resolve_workspace_path(relative_path))
        except (TypeError, ValueError) as exc:
            raise ValueError("Access denied: Path outside workspace.") from exc

    def read_file(self, relative_path: str) -> dict[str, object]:
        try:
            full_path = self._secure_path(relative_path)
            with open(full_path, "r", encoding="utf-8") as file_handle:
                return {"success": True, "content": file_handle.read()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def write_file(self, relative_path: str, content: str) -> dict[str, object]:
        try:
            full_path = self._secure_path(relative_path)
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as file_handle:
                file_handle.write(content)
            return {"success": True}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def get_tree(self, relative_path: str = "") -> dict[str, object]:
        try:
            full_path = self._secure_path(relative_path)
            items = []
            for item_name in sorted(os.listdir(full_path), key=str.lower):
                item_relative_path = os.path.join(relative_path, item_name)
                item_path = self._secure_path(item_relative_path)
                items.append(
                    {
                        "name": item_name,
                        "path": item_relative_path,
                        "is_dir": os.path.isdir(item_path),
                    }
                )
            return {"success": True, "items": items}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _copy_target(source: Path, destination_directory: Path) -> Path:
        """Return a new destination that never overwrites an existing item."""
        if source.is_dir():
            stem, suffix = source.name, ""
        else:
            stem, suffix = source.stem, source.suffix

        index = 1
        while True:
            copy_suffix = " - Copy" if index == 1 else f" - Copy {index}"
            target = destination_directory / f"{stem}{copy_suffix}{suffix}"
            if not target.exists():
                return target
            index += 1

    def copy_workspace_item(self, source_relative_path: str, destination_relative_path: str = "") -> dict[str, object]:
        """Copy a selected workspace item into a workspace folder safely."""
        try:
            source = Path(self._secure_path(source_relative_path))
            destination_directory = Path(self._secure_path(destination_relative_path))
            workspace_root = Path(self._secure_path(""))

            if not source.exists():
                raise FileNotFoundError("Selected workspace item was not found")
            if not destination_directory.is_dir():
                raise NotADirectoryError("Paste destination must be a workspace folder")
            if source.is_dir() and (destination_directory == source or source in destination_directory.parents):
                raise ValueError("A folder cannot be pasted into itself or one of its subfolders")
            if source.is_dir() and any(path.is_symlink() for path in source.rglob("*")):
                raise ValueError("Copying folders containing symbolic links is not supported")

            target = self._copy_target(source, destination_directory)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)

            return {
                "success": True,
                "path": target.relative_to(workspace_root).as_posix(),
                "is_dir": source.is_dir(),
            }
        except (OSError, TypeError, ValueError, PermissionError) as exc:
            return {"success": False, "error": str(exc)}

    def get_app_context(self) -> dict[str, object]:
        return {
            "success": True,
            "model": Config.MODEL,
            "project_path": Config.APPLICATION_PATH,
            "workspace_root": Config.WORKSPACE_ROOT,
            "workspace_configurable": True,
            "openai_key_source": Config.OPENAI_API_KEY_SOURCE,
            "secure_credentials_available": credential_store.available,
        }

    def choose_workspace(self) -> dict[str, object]:
        try:
            windows = getattr(webview, "windows", [])
            if not windows:
                return {"success": False, "cancelled": True, "error": "Desktop window is not ready."}
            selected = windows[0].create_file_dialog(
                webview.FOLDER_DIALOG,
                directory=Config.WORKSPACE_ROOT,
                allow_multiple=False,
            )
            if not selected:
                return {"success": False, "cancelled": True}
            workspace_root = save_workspace_root(str(selected[0]))
            return {"success": True, "workspace_root": workspace_root, "restart_required": True}
        except (OSError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    def get_preference(self, key: str, default: str | None = None) -> dict[str, object]:
        try:
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Preference key is required")
            return {"success": True, "key": key, "value": metadata_store.get(key, default)}
        except (OSError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    def set_preference(self, key: str, value: str) -> dict[str, object]:
        try:
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Preference key is required")
            if not isinstance(value, str):
                raise ValueError("Preference value must be text")
            return metadata_store.update(key, value)
        except (OSError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    def get_openai_credential_status(self) -> dict[str, object]:
        return credential_store.status("openai_api_key")

    def set_openai_api_key(self, api_key: str) -> dict[str, object]:
        result = credential_store.set("openai_api_key", api_key)
        if result.get("success"):
            result["restart_required"] = True
        return result

    def clear_openai_api_key(self) -> dict[str, object]:
        result = credential_store.delete("openai_api_key")
        if result.get("success"):
            result["restart_required"] = True
        return result

    @staticmethod
    def _validate_session_id(session_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", session_id):
            raise ValueError("Invalid session ID")
        return session_id

    def _session_path(self, session_id: str) -> Path:
        valid_id = self._validate_session_id(session_id)
        return Path(self._secure_path(os.path.join("sessions", f"{valid_id}.cmsession")))

    def save_session(self, session: dict[str, object]) -> dict[str, object]:
        try:
            if not isinstance(session, dict):
                raise ValueError("Session payload must be an object")
            session_id = self._validate_session_id(str(session.get("session_id", "")))
            payload = dict(session)
            payload["session_id"] = session_id
            payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()

            target = self._session_path(session_id)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
            return {
                "success": True,
                "session_id": session_id,
                "name": str(payload.get("name", session_id)),
                "file_name": target.name,
            }
        except (OSError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc)}

    def list_sessions(self) -> dict[str, object]:
        try:
            sessions_dir = Path(self._secure_path("sessions"))
            if not sessions_dir.exists():
                return {"success": True, "sessions": []}

            sessions: list[dict[str, object]] = []
            for path in sorted(sessions_dir.glob("*.cmsession"), key=lambda item: item.name.lower()):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("Session JSON must contain an object")
                    session_id = self._validate_session_id(str(payload.get("session_id", path.stem)))
                    sessions.append(
                        {
                            "session_id": session_id,
                            "name": str(payload.get("name", session_id)),
                            "timestamp": str(payload.get("updated_at", payload.get("timestamp", ""))),
                            "message_count": len(payload.get("conversation_history", [])),
                            "valid": True,
                        }
                    )
                except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
                    sessions.append(
                        {
                            "session_id": path.stem,
                            "name": path.name,
                            "timestamp": "",
                            "message_count": 0,
                            "valid": False,
                            "error": str(exc),
                        }
                    )
            return {"success": True, "sessions": sessions}
        except (OSError, TypeError, ValueError) as exc:
            return {"success": False, "error": str(exc), "sessions": []}

    def load_session(self, session_id: str) -> dict[str, object]:
        try:
            path = self._session_path(session_id)
            if not path.is_file():
                return {"success": False, "error": "Session file not found"}
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Session JSON must contain an object")
            return {"success": True, "session": payload}
        except FileNotFoundError:
            return {"success": False, "error": "Session file not found"}
        except (OSError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
            return {"success": False, "error": f"Unable to load session: {exc}"}


def main() -> None:
    """Start the Flask server and open the native desktop window."""
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire():
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                "Mighty Coding Machine is already running. Close the existing window before starting another instance.",
                "Mighty Coding Machine",
                0x40,
            )
        except (AttributeError, OSError):
            print("Mighty Coding Machine is already running.")
        return

    try:
        with socket.create_connection(("127.0.0.1", 5000), timeout=0.25):
            try:
                import ctypes

                ctypes.windll.user32.MessageBoxW(
                    0,
                    "A Mighty Coding Machine backend is already running on port 5000.",
                    "Mighty Coding Machine",
                    0x40,
                )
            except (AttributeError, OSError):
                print("A Mighty Coding Machine backend is already running on port 5000.")
            instance_lock.release()
            return
    except OSError:
        pass

    watcher: WorkspaceWatcher | None = None
    try:
        server_thread = threading.Thread(
            target=start_server,
            name="cm-flask-server",
            daemon=True,
        )
        server_thread.start()

        time.sleep(SERVER_STARTUP_DELAY_SECONDS)

        create_tray_icon()

        webview.create_window(
            "Mighty Coding Machine (MCM)",
            "http://127.0.0.1:5000",
            width=1440,
            height=900,
            min_size=(1024, 700),
            js_api=Api(),
        )

        watcher = WorkspaceWatcher(workspace_indexer)

        def start_workspace_services() -> None:
            watcher.start()
            start_workspace_indexing()

        webview.start(func=start_workspace_services, debug=False)
    finally:
        if watcher is not None:
            watcher.stop()
        instance_lock.release()


if __name__ == "__main__":
    if "--mcp-server" in sys.argv:
        from backend.mcp.server import main as start_mcp_server

        start_mcp_server()
    else:
        main()
