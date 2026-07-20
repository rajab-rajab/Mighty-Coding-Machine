"""Application exception types shared by backend layers."""

from __future__ import annotations


class CMException(Exception):
    status_code = 500


class PathTraversalError(CMException, PermissionError):
    status_code = 403


class CodeExecutionError(CMException):
    status_code = 500


class AgentError(CMException):
    status_code = 500

