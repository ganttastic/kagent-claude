"""Maps A2A contextId to Claude Agent SDK session_id for session continuity."""

from collections import OrderedDict
from typing import Protocol, runtime_checkable

# Default maximum number of sessions to keep in the in-memory store.
# Prevents unbounded memory growth for long-running pods.
DEFAULT_MAX_SESSIONS = 1024


@runtime_checkable
class SessionStore(Protocol):
    """Protocol for session stores.

    Implement this to provide custom persistence (Redis, database,
    kagent controller API) for session mappings that survive pod restarts.

    Example::

        class RedisSessionStore:
            def __init__(self, redis_client):
                self._redis = redis_client

            def get(self, context_id: str) -> str | None:
                return self._redis.get(f"claude:session:{context_id}")

            def set(self, context_id: str, claude_session_id: str) -> None:
                self._redis.set(f"claude:session:{context_id}", claude_session_id)

            def delete(self, context_id: str) -> None:
                self._redis.delete(f"claude:session:{context_id}")
    """

    def get(self, context_id: str) -> str | None:
        """Return the Claude session_id for a given A2A contextId, or None."""
        ...

    def set(self, context_id: str, claude_session_id: str) -> None:
        """Persist the mapping after a new Claude session is created."""
        ...

    def delete(self, context_id: str) -> None:
        """Remove a mapping."""
        ...


class ClaudeSessionStore:
    """
    In-memory LRU session store mapping A2A contextId -> Claude session_id.

    Implements the ``SessionStore`` protocol. Uses an ``OrderedDict`` for
    LRU eviction — when ``max_sessions`` is reached, the oldest (least
    recently used) entry is evicted.

    For persistence across pod restarts, substitute a custom implementation
    of the ``SessionStore`` protocol (e.g., backed by Redis or the kagent
    controller's session API).
    """

    def __init__(self, max_sessions: int = DEFAULT_MAX_SESSIONS):
        self._store: OrderedDict[str, str] = OrderedDict()
        self._max_sessions = max_sessions

    def get(self, context_id: str) -> str | None:
        """Return the Claude session_id for a given A2A contextId, or None."""
        value = self._store.get(context_id)
        if value is not None:
            # Move to end (most recently used)
            self._store.move_to_end(context_id)
        return value

    def set(self, context_id: str, claude_session_id: str) -> None:
        """Persist the mapping after a new Claude session is created."""
        if context_id in self._store:
            self._store.move_to_end(context_id)
        self._store[context_id] = claude_session_id
        # Evict oldest if over capacity
        while len(self._store) > self._max_sessions:
            self._store.popitem(last=False)

    def delete(self, context_id: str) -> None:
        """Remove a mapping."""
        self._store.pop(context_id, None)
