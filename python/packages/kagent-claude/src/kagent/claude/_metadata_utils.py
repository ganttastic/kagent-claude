"""
Rich metadata utilities for A2A events.

Provides namespaced metadata keys consistent with kagent conventions,
enabling structured observability in the kagent dashboard.
"""

from datetime import datetime, timezone
from typing import Any


# Namespace prefix for all kagent-claude metadata
_PREFIX = "kagent.claude"


def execution_metadata(
    *,
    app_name: str,
    session_id: str | None = None,
    claude_session_id: str | None = None,
    is_resume: bool = False,
) -> dict[str, Any]:
    """Build metadata for execution start events."""
    meta: dict[str, Any] = {
        f"{_PREFIX}.app_name": app_name,
        f"{_PREFIX}.timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if session_id:
        meta[f"{_PREFIX}.session_id"] = session_id
    if claude_session_id:
        meta[f"{_PREFIX}.claude_session_id"] = claude_session_id
    if is_resume:
        meta[f"{_PREFIX}.is_resume"] = True
    return meta


def completion_metadata(
    *,
    session_id: str | None = None,
    claude_session_id: str | None = None,
    message_count: int = 0,
    result_length: int = 0,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    """Build metadata for task completion events."""
    meta: dict[str, Any] = {
        f"{_PREFIX}.message_count": message_count,
        f"{_PREFIX}.result_length": result_length,
        f"{_PREFIX}.timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if session_id:
        meta[f"{_PREFIX}.session_id"] = session_id
    if claude_session_id:
        meta[f"{_PREFIX}.claude_session_id"] = claude_session_id
    if duration_ms is not None:
        meta[f"{_PREFIX}.duration_ms"] = round(duration_ms, 2)
    return meta


def streaming_metadata(
    *,
    message_index: int,
    message_type: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Build metadata for streaming intermediate events."""
    meta: dict[str, Any] = {
        f"{_PREFIX}.message_index": message_index,
        f"{_PREFIX}.message_type": message_type,
    }
    if tool_name:
        meta[f"{_PREFIX}.tool_name"] = tool_name
    return meta


def error_metadata(
    *,
    error_type: str,
    error_detail: str,
    is_transient: bool = False,
) -> dict[str, Any]:
    """Build metadata for error events."""
    return {
        f"{_PREFIX}.error_type": error_type,
        f"{_PREFIX}.error_detail": error_detail,
        f"{_PREFIX}.error_transient": is_transient,
        f"{_PREFIX}.timestamp": datetime.now(timezone.utc).isoformat(),
    }
