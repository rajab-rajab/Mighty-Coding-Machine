"""Deterministic capability recommendations for MCM agent requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class CapabilityRecommendation:
    """A transparent, least-privilege recommendation for one request."""

    agent: str
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    reason: str
    confidence: float

    def public(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "skills": list(self.skills),
            "tools": list(self.tools),
            "reason": self.reason,
            "confidence": self.confidence,
        }


class CapabilityRouter:
    """Recommend a specialist, scoped Skills, and supporting tools from request intent."""

    _LANGUAGE_SKILLS = (
        (("typescript", ".ts", ".tsx"), "typescript"),
        (("javascript", "node.js", "node ", ".js", ".jsx"), "javascript"),
        (("python", "flask", "fastapi", "django", ".py"), "python"),
        (("html", "css", "accessibility", "responsive"), "html-css"),
        (("java", "spring boot"), "java"),
        (("c#", ".net", "asp.net"), "csharp"),
        (("c++", " c ", "cmake"), "c-cpp"),
        (("golang", " go "), "go"),
        (("rust", "cargo"), "rust"),
        (("php", "laravel"), "php"),
        (("ruby", "rails"), "ruby"),
        (("kotlin", "android"), "kotlin"),
        (("swift", "ios", "macos"), "swift"),
    )

    _EXISTING_CODEBASE_TERMS = (
        "existing",
        "current",
        "workspace",
        "codebase",
        "repository",
        "repo",
        "update",
        "modify",
        "fix",
        "bug",
        "error",
        "refactor",
    )

    def recommend(self, message: str) -> CapabilityRecommendation:
        """Return a predictable recommendation without an additional model call."""
        text = str(message or "").lower()
        skills: list[str] = []
        tools: list[str] = []
        agent = "Code Agent"
        reason = "General implementation request."
        confidence = 0.72

        if self._matches(text, ("security", "vulnerability", "cve", "secret", "authentication", "authorization", "permissions", "path traversal", "injection")):
            agent = "Security Agent"
            skills.extend(("security-audit", "codebase-rag"))
            tools.extend(("project-inventory", "dependency-manifest", "workspace-search"))
            reason = "Security-sensitive request detected."
            confidence = 0.94
        elif self._matches(text, ("deploy", "deployment", "release", "publish", "package", "packaging", "pyinstaller", "docker")):
            agent = "Deployment Agent"
            skills.extend(("windows-packaging", "documentation"))
            tools.extend(("project-inventory", "dependency-manifest", "request-deployment-approval"))
            reason = "Packaging or deployment request detected."
            confidence = 0.93
        elif self._matches(text, ("git", "commit", "branch", "merge", "rebase", "push", "pull", "repository", "source control")):
            agent = "Git Agent"
            skills.append("git-workflow")
            tools.extend(("git-status", "git-diff", "git-history"))
            reason = "Explicit source-control request detected."
            confidence = 0.93
        elif self._is_complex(text):
            agent = "Planner Agent"
            skills.append("requirements-planning")
            tools.extend(("create-plan", "project-inventory"))
            reason = "Multi-step request benefits from structured planning."
            confidence = 0.87
        elif self._matches(text, ("sql", "database", "schema", "table", "query", "postgres", "postgresql", "mysql", "sqlite")):
            agent = "Database Agent"
            skills.append("database-engineering")
            if "sqlite" in text:
                skills.append("sqlite")
            tools.extend(("db-list-tables", "db-execute-query"))
            reason = "Database or SQL request detected."
            confidence = 0.91
        elif self._matches(text, ("debug", "bug", "error", "traceback", "exception", "failing", "not working", "crash")):
            agent = "Debug Agent"
            skills.extend(("debugging", "codebase-rag"))
            tools.extend(("analyze-error", "workspace-search", "python-syntax-check"))
            reason = "Failure-analysis request detected."
            confidence = 0.9
        elif self._matches(text, ("test", "pytest", "unit test", "integration test", "coverage", "verify")):
            agent = "Test Agent"
            skills.append("testing-quality")
            tools.extend(("project-inventory", "python-syntax-check", "run-tests"))
            reason = "Testing or verification request detected."
            confidence = 0.89
        elif self._matches(text, ("documentation", "readme", "demo", "guide", "manual")):
            skills.append("documentation")
            tools.extend(("project-inventory", "workspace-search", "file-read"))
            reason = "Documentation request detected."
            confidence = 0.86
        elif self._matches(text, ("frontend", "html", "css", "javascript", "ui", "ux", "browser", "react", "alpine", "monaco")):
            agent = "Frontend Agent"
            skills.append("frontend-ui")
            tools.extend(("workspace-search", "file-read"))
            reason = "Frontend or user-interface request detected."
            confidence = 0.88

        skills.extend(self._language_skills(text))
        if self._matches(text, self._EXISTING_CODEBASE_TERMS) and "codebase-rag" not in skills:
            skills.append("codebase-rag")
            tools.extend(("codebase-search", "workspace-search"))

        return CapabilityRecommendation(
            agent=agent,
            skills=tuple(self._unique(skills)),
            tools=tuple(self._unique(tools)),
            reason=reason,
            confidence=confidence,
        )

    @staticmethod
    def _matches(text: str, terms: Iterable[str]) -> bool:
        return any(term in text for term in terms)

    @classmethod
    def _language_skills(cls, text: str) -> list[str]:
        return [skill_id for terms, skill_id in cls._LANGUAGE_SKILLS if cls._matches(text, terms)]

    @staticmethod
    def _is_complex(text: str) -> bool:
        return (
            text.count("\n") >= 2
            or len(text) >= 280
            or any(term in text for term in ("end-to-end", "multi-step", "multiple files", "with tests", "full application"))
        )

    @staticmethod
    def _unique(values: Iterable[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))


__all__ = ["CapabilityRecommendation", "CapabilityRouter"]
