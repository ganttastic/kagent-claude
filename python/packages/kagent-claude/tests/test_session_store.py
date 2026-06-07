"""Tests for ClaudeSessionStore and SessionStore protocol."""

from kagent.claude._session_store import ClaudeSessionStore, SessionStore


def test_get_returns_none_on_miss():
    store = ClaudeSessionStore()
    assert store.get("unknown-context") is None


def test_set_and_get_roundtrip():
    store = ClaudeSessionStore()
    store.set("ctx-1", "claude-sess-abc")
    assert store.get("ctx-1") == "claude-sess-abc"


def test_set_overwrites_existing():
    store = ClaudeSessionStore()
    store.set("ctx-1", "sess-1")
    store.set("ctx-1", "sess-2")
    assert store.get("ctx-1") == "sess-2"


def test_delete_removes_mapping():
    store = ClaudeSessionStore()
    store.set("ctx-1", "sess-1")
    store.delete("ctx-1")
    assert store.get("ctx-1") is None


def test_delete_nonexistent_is_noop():
    store = ClaudeSessionStore()
    store.delete("nonexistent")  # should not raise


# --- LRU eviction tests ---


def test_lru_evicts_oldest_when_full():
    store = ClaudeSessionStore(max_sessions=3)
    store.set("ctx-1", "sess-1")
    store.set("ctx-2", "sess-2")
    store.set("ctx-3", "sess-3")
    # Adding a 4th should evict ctx-1
    store.set("ctx-4", "sess-4")
    assert store.get("ctx-1") is None
    assert store.get("ctx-2") == "sess-2"
    assert store.get("ctx-4") == "sess-4"


def test_lru_get_refreshes_entry():
    store = ClaudeSessionStore(max_sessions=3)
    store.set("ctx-1", "sess-1")
    store.set("ctx-2", "sess-2")
    store.set("ctx-3", "sess-3")
    # Access ctx-1 to make it most recently used
    store.get("ctx-1")
    # Adding ctx-4 should now evict ctx-2 (oldest untouched)
    store.set("ctx-4", "sess-4")
    assert store.get("ctx-1") == "sess-1"
    assert store.get("ctx-2") is None


def test_lru_overwrite_refreshes_entry():
    store = ClaudeSessionStore(max_sessions=3)
    store.set("ctx-1", "sess-1")
    store.set("ctx-2", "sess-2")
    store.set("ctx-3", "sess-3")
    # Overwrite ctx-1 to refresh it
    store.set("ctx-1", "sess-1-updated")
    # Adding ctx-4 should evict ctx-2
    store.set("ctx-4", "sess-4")
    assert store.get("ctx-1") == "sess-1-updated"
    assert store.get("ctx-2") is None


def test_default_max_sessions_is_large():
    store = ClaudeSessionStore()
    # Default should be 1024 — just verify it doesn't evict at small counts
    for i in range(100):
        store.set(f"ctx-{i}", f"sess-{i}")
    assert store.get("ctx-0") == "sess-0"
    assert store.get("ctx-99") == "sess-99"


# --- Protocol conformance ---


def test_session_store_protocol_conformance():
    """ClaudeSessionStore satisfies the SessionStore protocol."""
    store = ClaudeSessionStore()
    assert isinstance(store, SessionStore)


def test_custom_store_satisfies_protocol():
    """A custom implementation satisfies the SessionStore protocol."""

    class DictStore:
        def __init__(self):
            self._d = {}

        def get(self, context_id: str) -> str | None:
            return self._d.get(context_id)

        def set(self, context_id: str, claude_session_id: str) -> None:
            self._d[context_id] = claude_session_id

        def delete(self, context_id: str) -> None:
            self._d.pop(context_id, None)

    store = DictStore()
    assert isinstance(store, SessionStore)
