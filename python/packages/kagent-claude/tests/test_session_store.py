"""Tests for ClaudeSessionStore."""

from kagent.claude._session_store import ClaudeSessionStore


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
