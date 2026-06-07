"""Tests for _extract_text helper."""

from unittest.mock import MagicMock

from kagent.claude._executor import _extract_text


def test_extract_text_from_text_part():
    """TextPart with .text attribute."""
    part = MagicMock()
    part.text = "Hello world"
    # Remove root attr so it doesn't match that branch
    del part.root

    message = MagicMock()
    message.parts = [part]

    assert _extract_text(message) == "Hello world"


def test_extract_text_from_root_text():
    """Part with .root.text (Pydantic union wrapper)."""
    root = MagicMock()
    root.text = "From root"

    part = MagicMock(spec=[])  # no .text attribute
    part.root = root

    message = MagicMock()
    message.parts = [part]

    assert _extract_text(message) == "From root"


def test_extract_text_empty_parts():
    """Empty parts list returns empty string."""
    message = MagicMock()
    message.parts = []
    assert _extract_text(message) == ""


def test_extract_text_no_parts_attribute():
    """Message without parts attribute returns empty string."""
    message = MagicMock(spec=[])
    assert _extract_text(message) == ""
