"""Safe Git operations scoped to the configured workspace."""

from __future__ import annotations

import difflib
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from ..config import WORKSPACE_PATH
from ..security import validate_path


class GitManager:
    """Run non-interactive Git commands without allowing shell execution."""

    def __init__(self, workspace_root: str | Path = WORKSPACE_PATH, timeout: float = 15.0) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.timeout = timeout

    def _workspace_path(self, relative_path: str = "") -> Path:
        return Path(validate_path(relative_path or ".", self.workspace_root))

    def _git(self, arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        environment = {
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_PAGER": "cat",
            "PAGER": "cat",
            "GIT_OPTIONAL_LOCKS": "0",
        }
        startupinfo = None
        creationflags = 0
        if os.name == "nt":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        return subprocess.run(
            ["git", *arguments],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.timeout,
            check=False,
            shell=False,
            env={**os.environ, **environment},
            startupinfo=startupinfo,
            creationflags=creationflags,
        )

    @staticmethod
    def _diff_lines(diff: str) -> list[dict[str, str]]:
        lines = []
        for line in diff.splitlines():
            if line.startswith("+++") or line.startswith("---"):
                line_type = "header"
            elif line.startswith("@@"):
                line_type = "hunk"
            elif line.startswith("+"):
                line_type = "added"
            elif line.startswith("-"):
                line_type = "removed"
            else:
                line_type = "context"
            lines.append({"type": line_type, "text": line})
        return lines

    @staticmethod
    def _valid_ref(value: str, kind: str) -> tuple[bool, str]:
        clean = str(value or "").strip()
        if not clean or clean.startswith("-"):
            return False, f"{kind} is required."
        if any(character.isspace() for character in clean):
            return False, f"Invalid {kind.lower()}."
        return True, clean

    def _repo_root(self, scope: Path) -> tuple[Path | None, dict[str, Any] | None]:
        try:
            result = self._git(["-C", str(scope), "rev-parse", "--show-toplevel"], self.workspace_root)
        except FileNotFoundError:
            return None, {"success": False, "available": False, "error": "Git is not installed or not on PATH."}
        except subprocess.TimeoutExpired:
            return None, {"success": False, "available": True, "error": "Git command timed out."}
        if result.returncode != 0:
            return None, {
                "success": True,
                "available": True,
                "is_repo": False,
                "error": "The workspace is not inside a Git repository.",
            }
        return Path(result.stdout.strip()).resolve(), None

    def _scope(self, project_path: str = "") -> tuple[Path | None, Path | None, dict[str, Any] | None]:
        try:
            scope = self._workspace_path(project_path)
        except (PermissionError, ValueError) as exc:
            return None, None, {"success": False, "available": True, "error": str(exc)}
        repo_root, error = self._repo_root(scope)
        if error:
            return None, None, error
        if repo_root is None:
            return None, None, {"success": False, "available": True, "error": "Git repository not found."}
        try:
            scope.relative_to(repo_root)
        except ValueError:
            return None, None, {"success": False, "available": True, "error": "Repository scope is invalid."}
        return repo_root, scope, None

    @staticmethod
    def _repo_relative(path: Path, repo_root: Path) -> str:
        return path.relative_to(repo_root).as_posix()

    @staticmethod
    def _workspace_relative(path: Path, workspace_root: Path) -> str:
        return path.relative_to(workspace_root).as_posix()

    def status(self, project_path: str = "") -> dict[str, Any]:
        repo_root, scope, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None and scope is not None
        try:
            result = self._git(["status", "--porcelain=v1", "--branch", "--untracked-files=all"], repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        if result.returncode != 0:
            return {"success": False, "available": True, "error": result.stderr.strip() or "Unable to read Git status."}

        branch = ""
        changes: list[dict[str, Any]] = []
        for line in result.stdout.splitlines():
            if line.startswith("## "):
                branch = line[3:].strip()
                continue
            if len(line) < 4 or line[:2] == "!!":
                continue
            code = line[:2]
            display_path = line[3:].strip()
            if " -> " in display_path:
                display_path = display_path.rsplit(" -> ", 1)[-1]
            changed_path = (repo_root / display_path).resolve()
            try:
                changed_path.relative_to(scope)
            except ValueError:
                continue
            try:
                workspace_path = self._workspace_relative(changed_path, self.workspace_root)
            except ValueError:
                continue
            changes.append(
                {
                    "path": workspace_path,
                    "repo_path": self._repo_relative(changed_path, repo_root),
                    "status": code,
                    "index_status": code[0],
                    "worktree_status": code[1],
                    "staged": code[0] not in {" ", "?"},
                    "untracked": code == "??",
                }
            )
        branch_info = self.branches(project_path="", _repo_root=repo_root)
        remote_info = self.remotes(_repo_root=repo_root)
        return {
            "success": True,
            "available": True,
            "is_repo": True,
            "branch": branch,
            "repo_root": str(repo_root),
            "changes": changes,
            "current_branch": branch_info.get("current", branch),
            "branches": branch_info.get("branches", []),
            "remotes": remote_info.get("remotes", []),
        }

    def init(self, project_path: str = "") -> dict[str, Any]:
        try:
            target = self._workspace_path(project_path)
            target.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError, ValueError) as exc:
            return {"success": False, "available": True, "error": str(exc)}
        try:
            result = self._git(["init"], target)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        return {
            "success": result.returncode == 0,
            "available": True,
            "repo_root": str(target.resolve()),
            "output": result.stdout.strip() or result.stderr.strip(),
            "error": result.stderr.strip() if result.returncode else "",
        }

    def branches(self, project_path: str = "", _repo_root: Path | None = None) -> dict[str, Any]:
        repo_root = _repo_root
        if repo_root is None:
            repo_root, _, error = self._scope(project_path)
            if error:
                return error
        assert repo_root is not None
        try:
            result = self._git(["branch", "--format=%(refname:short)"], repo_root)
            current = self._git(["branch", "--show-current"], repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        if result.returncode != 0 or current.returncode != 0:
            return {"success": False, "available": True, "error": result.stderr.strip() or current.stderr.strip()}
        return {
            "success": True,
            "available": True,
            "branches": [line.strip() for line in result.stdout.splitlines() if line.strip()],
            "current": current.stdout.strip(),
        }

    def switch_branch(self, branch: str, project_path: str = "") -> dict[str, Any]:
        valid, clean_branch = self._valid_ref(branch, "Branch")
        if not valid:
            return {"success": False, "available": True, "error": clean_branch}
        repo_root, _, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None
        try:
            result = self._git(["switch", clean_branch], repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        return {
            "success": result.returncode == 0,
            "available": True,
            "branch": clean_branch,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode else "",
        }

    def history(self, project_path: str = "", limit: int = 25) -> dict[str, Any]:
        repo_root, _, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None
        try:
            safe_limit = max(1, min(int(limit), 100))
            result = self._git(
                ["log", f"--max-count={safe_limit}", "--date=iso-strict", "--pretty=format:%H%x09%h%x09%an%x09%aI%x09%s"],
                repo_root,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        if result.returncode != 0:
            if "does not have any commits" in result.stderr.lower():
                return {"success": True, "available": True, "history": []}
            return {"success": False, "available": True, "history": [], "error": result.stderr.strip()}
        commits = []
        for line in result.stdout.splitlines():
            parts = line.split("\t", 4)
            if len(parts) == 5:
                commits.append({"hash": parts[0], "short_hash": parts[1], "author": parts[2], "date": parts[3], "subject": parts[4]})
        return {"success": True, "available": True, "history": commits}

    def remotes(self, _repo_root: Path | None = None, project_path: str = "") -> dict[str, Any]:
        repo_root = _repo_root
        if repo_root is None:
            repo_root, _, error = self._scope(project_path)
            if error:
                return error
        assert repo_root is not None
        try:
            result = self._git(["remote", "-v"], repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        if result.returncode != 0:
            return {"success": False, "available": True, "error": result.stderr.strip()}
        remotes: dict[str, dict[str, str]] = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^(\S+)\s+(\S+)\s+\((fetch|push)\)$", line)
            if not match:
                continue
            name, url, direction = match.groups()
            remotes.setdefault(name, {})[direction] = url
        return {"success": True, "available": True, "remotes": [{"name": name, **values} for name, values in remotes.items()]}

    def push(self, remote: str = "origin", branch: str = "", project_path: str = "") -> dict[str, Any]:
        return self._remote_action("push", remote, branch, project_path)

    def pull(self, remote: str = "origin", branch: str = "", project_path: str = "") -> dict[str, Any]:
        return self._remote_action("pull", remote, branch, project_path)

    def _remote_action(self, action: str, remote: str, branch: str, project_path: str) -> dict[str, Any]:
        valid_remote, clean_remote = self._valid_ref(remote, "Remote")
        if not valid_remote:
            return {"success": False, "available": True, "error": clean_remote}
        repo_root, _, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None
        if not branch:
            branch_result = self.branches(_repo_root=repo_root)
            branch = branch_result.get("current", "")
        valid_branch, clean_branch = self._valid_ref(branch, "Branch")
        if not valid_branch:
            return {"success": False, "available": True, "error": clean_branch}
        arguments = [action, "--ff-only", clean_remote, clean_branch] if action == "pull" else [action, "--set-upstream", clean_remote, clean_branch]
        try:
            result = self._git(arguments, repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        return {
            "success": result.returncode == 0,
            "available": True,
            "action": action,
            "remote": clean_remote,
            "branch": clean_branch,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode else "",
        }

    def diff(self, relative_path: str = "", staged: bool = False, project_path: str = "") -> dict[str, Any]:
        try:
            target = self._workspace_path(relative_path)
        except (PermissionError, ValueError) as exc:
            return {"success": False, "available": True, "error": str(exc)}
        repo_root, _, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None
        try:
            repo_path = self._repo_relative(target, repo_root)
        except (PermissionError, ValueError) as exc:
            return {"success": False, "available": True, "error": str(exc)}
        arguments = ["diff"]
        if staged:
            arguments.append("--cached")
        arguments.extend(["--no-ext-diff", "--", repo_path])
        try:
            status_result = self._git(["status", "--porcelain=v1", "--", repo_path], repo_root)
            if not staged and status_result.stdout.startswith("??") and target.is_file():
                content = target.read_text(encoding="utf-8")
                diff = "".join(
                    difflib.unified_diff(
                        [],
                        content.splitlines(keepends=True),
                        fromfile="/dev/null",
                        tofile=f"b/{repo_path}",
                    )
                )
                return {
                    "success": True,
                    "available": True,
                    "path": relative_path,
                    "staged": staged,
                    "diff": diff,
                    "diff_lines": self._diff_lines(diff),
                    "error": "",
                }
            result = self._git(arguments, repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError, UnicodeError) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        return {
            "success": result.returncode == 0,
            "available": True,
            "path": relative_path,
            "staged": staged,
            "diff": result.stdout,
            "diff_lines": self._diff_lines(result.stdout),
            "error": result.stderr.strip() if result.returncode else "",
        }

    def _change(self, action: str, relative_path: str, project_path: str = "") -> dict[str, Any]:
        try:
            target = self._workspace_path(relative_path)
        except (PermissionError, ValueError) as exc:
            return {"success": False, "available": True, "error": str(exc)}
        repo_root, _, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None
        try:
            repo_path = self._repo_relative(target, repo_root)
        except (PermissionError, ValueError) as exc:
            return {"success": False, "available": True, "error": str(exc)}
        if action == "stage":
            arguments = ["add", "--", repo_path]
        else:
            arguments = ["restore", "--staged", "--", repo_path]
        try:
            result = self._git(arguments, repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        return {"success": result.returncode == 0, "error": result.stderr.strip() if result.returncode else ""}

    def stage(self, relative_path: str, project_path: str = "") -> dict[str, Any]:
        return self._change("stage", relative_path, project_path)

    def unstage(self, relative_path: str, project_path: str = "") -> dict[str, Any]:
        return self._change("unstage", relative_path, project_path)

    def commit(self, message: str, project_path: str = "") -> dict[str, Any]:
        clean_message = str(message or "").strip()
        if not clean_message:
            return {"success": False, "error": "Commit message is required."}
        if len(clean_message) > 500:
            return {"success": False, "error": "Commit message is too long."}
        repo_root, _, error = self._scope(project_path)
        if error:
            return error
        assert repo_root is not None
        try:
            result = self._git(["commit", "-m", clean_message, "--"], repo_root)
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return {"success": False, "available": False, "error": str(exc)}
        return {
            "success": result.returncode == 0,
            "output": result.stdout.strip(),
            "error": result.stderr.strip() if result.returncode else "",
        }


source_control = GitManager()
