"""Tests for error classification module."""

import asyncio

from kagent.claude._error_mappings import classify_error


def test_classify_rate_limit():
    error = RuntimeError("rate_limit_error: too many requests")
    classified = classify_error(error)
    assert classified.error_type == "rate_limit"
    assert classified.is_transient is True
    assert "rate-limited" in classified.user_message


def test_classify_auth_error():
    error = RuntimeError("401 Unauthorized: invalid x-api-key")
    classified = classify_error(error)
    assert classified.error_type == "auth"
    assert classified.is_transient is False
    assert "API key" in classified.user_message


def test_classify_context_overflow():
    error = RuntimeError("prompt is too long: exceeds maximum context length")
    classified = classify_error(error)
    assert classified.error_type == "context_overflow"
    assert classified.is_transient is False


def test_classify_network_error():
    error = ConnectionError("Connection refused")
    classified = classify_error(error)
    assert classified.error_type == "network"
    assert classified.is_transient is True


def test_classify_timeout():
    error = asyncio.TimeoutError()
    classified = classify_error(error)
    assert classified.error_type == "timeout"
    assert classified.is_transient is True


def test_classify_unknown():
    error = ValueError("something weird happened")
    classified = classify_error(error)
    assert classified.error_type == "unknown"
    assert classified.is_transient is False
    assert "ValueError" in classified.user_message


def test_classify_cli_not_found():
    error = FileNotFoundError("claude: command not found")
    classified = classify_error(error)
    assert classified.error_type == "cli_not_found"
    assert classified.is_transient is False


def test_classify_permission():
    error = PermissionError("Permission denied: /etc/shadow")
    classified = classify_error(error)
    assert classified.error_type == "permission"
    assert classified.is_transient is False
