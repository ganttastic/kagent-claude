"""Maps A2A contextId to Claude Agent SDK session_id for session continuity."""


class ClaudeSessionStore:
    """
    Maps A2A contextId -> Claude Agent SDK session_id.

    Starts as in-memory. Can be extended to Redis or the kagent
    controller's session API for persistence across pod restarts.
    """

    def __init__(self):
        self._store: dict[str, str] = {}

    def get(self, context_id: str) -> str | None:
        """Return the Claude session_id for a given A2A contextId, or None."""
        return self._store.get(context_id)

    def set(self, context_id: str, claude_session_id: str) -> None:
        """Persist the mapping after a new Claude session is created."""
        self._store[context_id] = claude_session_id

    def delete(self, context_id: str) -> None:
        """Remove a mapping."""
        self._store.pop(context_id, None)
