"""Error classification and user-friendly error messages for Claude Agent SDK errors."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Claude Agent SDK specific error patterns
_ANTHROPIC_RATE_LIMIT_PATTERNS = (
    "rate_limit",
    "429",
    "too many requests",
    "overloaded",
)

_ANTHROPIC_AUTH_PATTERNS = (
    "authentication",
    "unauthorized",
    "invalid api key",
    "401",
    "invalid x-api-key",
)

_ANTHROPIC_CONTEXT_PATTERNS = (
    "context window",
    "too many tokens",
    "maximum context length",
    "prompt is too long",
)

_NETWORK_PATTERNS = (
    "connection",
    "timeout",
    "dns",
    "ssl",
    "certificate",
    "network",
)

_PERMISSION_PATTERNS = (
    "permission denied",
    "not allowed",
    "forbidden",
    "403",
)

_CLI_NOT_FOUND_PATTERNS = (
    "cli not found",
    "command not found",
    "no such file or directory",
    "claude: not found",
)


@dataclass
class ClassifiedError:
    """A classified error with user-friendly message and structured metadata."""

    error_type: str
    user_message: str
    detail: str
    is_transient: bool = False


def classify_error(exception: Exception) -> ClassifiedError:
    """
    Classify an exception into a user-friendly error with structured metadata.

    Returns a ClassifiedError with:
    - error_type: machine-readable category (e.g., "rate_limit", "auth", "timeout")
    - user_message: what to show the user
    - detail: raw exception info for debugging
    - is_transient: whether this error might succeed on retry
    """
    error_str = str(exception).lower()
    error_class = type(exception).__name__
    raw_detail = f"{error_class}: {exception}"

    # Rate limiting
    if any(p in error_str for p in _ANTHROPIC_RATE_LIMIT_PATTERNS):
        return ClassifiedError(
            error_type="rate_limit",
            user_message="Claude is currently rate-limited. The request will be retried automatically.",
            detail=raw_detail,
            is_transient=True,
        )

    # Authentication errors
    if any(p in error_str for p in _ANTHROPIC_AUTH_PATTERNS):
        return ClassifiedError(
            error_type="auth",
            user_message="Authentication failed. Please verify the Anthropic API key is valid.",
            detail=raw_detail,
            is_transient=False,
        )

    # Context window exceeded
    if any(p in error_str for p in _ANTHROPIC_CONTEXT_PATTERNS):
        return ClassifiedError(
            error_type="context_overflow",
            user_message="The conversation exceeded Claude's context window. Please start a new conversation.",
            detail=raw_detail,
            is_transient=False,
        )

    # Network / connectivity
    if any(p in error_str for p in _NETWORK_PATTERNS):
        return ClassifiedError(
            error_type="network",
            user_message="A network error occurred while communicating with Claude. This may be transient.",
            detail=raw_detail,
            is_transient=True,
        )

    # Permission denied (tool execution)
    if any(p in error_str for p in _PERMISSION_PATTERNS):
        return ClassifiedError(
            error_type="permission",
            user_message="A tool execution was denied due to insufficient permissions.",
            detail=raw_detail,
            is_transient=False,
        )

    # CLI not found
    if any(p in error_str for p in _CLI_NOT_FOUND_PATTERNS):
        return ClassifiedError(
            error_type="cli_not_found",
            user_message="The Claude Agent SDK CLI binary was not found. Ensure claude-agent-sdk is installed correctly.",
            detail=raw_detail,
            is_transient=False,
        )

    # Timeout (asyncio)
    if isinstance(exception, (TimeoutError, asyncio.TimeoutError)):
        return ClassifiedError(
            error_type="timeout",
            user_message="The Claude query timed out. The task may be too complex or Claude may be slow to respond.",
            detail=raw_detail,
            is_transient=True,
        )

    # Cancellation
    if isinstance(exception, asyncio.CancelledError):
        return ClassifiedError(
            error_type="cancelled",
            user_message="The task was cancelled.",
            detail=raw_detail,
            is_transient=False,
        )

    # Process error (CLI exited non-zero)
    if "exit code" in error_str or "process" in error_str:
        return ClassifiedError(
            error_type="process_error",
            user_message="The Claude process exited unexpectedly. This may indicate a configuration issue.",
            detail=raw_detail,
            is_transient=True,
        )

    # JSON decode error (malformed response from CLI)
    if "json" in error_str and ("decode" in error_str or "parse" in error_str):
        return ClassifiedError(
            error_type="parse_error",
            user_message="Failed to parse Claude's response. This is usually a transient issue.",
            detail=raw_detail,
            is_transient=True,
        )

    # Unknown / generic
    return ClassifiedError(
        error_type="unknown",
        user_message=f"An unexpected error occurred: {error_class}",
        detail=raw_detail,
        is_transient=False,
    )


def get_error_metadata(classified: ClassifiedError) -> dict:
    """Build structured error metadata for A2A event metadata."""
    return {
        "kagent.error_type": classified.error_type,
        "kagent.error_detail": classified.detail,
        "kagent.error_transient": classified.is_transient,
    }


# Required for asyncio.TimeoutError reference
import asyncio  # noqa: E402
