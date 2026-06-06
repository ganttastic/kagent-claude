"""Tests for message converters module."""

from unittest.mock import MagicMock

import pytest

from kagent.claude._converters import (
    StreamingEventEmitter,
    classify_sdk_message,
    convert_assistant_message,
    convert_message_to_parts,
    make_message_id,
)


class TestClassifySdkMessage:
    def test_system_message(self):
        msg = MagicMock()
        type(msg).__name__ = "SystemMessage"
        assert classify_sdk_message(msg) == "system"

    def test_assistant_message(self):
        msg = MagicMock()
        type(msg).__name__ = "AssistantMessage"
        assert classify_sdk_message(msg) == "assistant"

    def test_user_message(self):
        msg = MagicMock()
        type(msg).__name__ = "UserMessage"
        assert classify_sdk_message(msg) == "user"

    def test_result_message(self):
        msg = MagicMock()
        type(msg).__name__ = "ResultMessage"
        assert classify_sdk_message(msg) == "result"

    def test_unknown_message(self):
        msg = MagicMock()
        type(msg).__name__ = "SomethingElse"
        assert classify_sdk_message(msg) == "unknown"


class TestConvertAssistantMessage:
    def test_text_block(self):
        block = MagicMock()
        block.type = "text"
        block.text = "Hello world"

        msg = MagicMock()
        msg.content = [block]

        parts = convert_assistant_message(msg)
        assert parts is not None
        assert len(parts) == 1

    def test_tool_use_block(self):
        block = MagicMock()
        block.type = "tool_use"
        block.name = "Bash"
        block.input = {"command": "ls"}
        block.id = "tool-123"

        msg = MagicMock()
        msg.content = [block]

        parts = convert_assistant_message(msg)
        assert parts is not None
        assert len(parts) == 1
        # The DataPart should contain tool info
        part = parts[0]
        inner = part.root if hasattr(part, "root") else part
        assert inner.data["name"] == "Bash"
        assert inner.data["args"] == {"command": "ls"}

    def test_empty_content(self):
        msg = MagicMock()
        msg.content = []
        assert convert_assistant_message(msg) is None

    def test_no_content(self):
        msg = MagicMock(spec=[])
        assert convert_assistant_message(msg) is None


class TestConvertMessageToParts:
    def test_system_message_returns_none(self):
        msg = MagicMock()
        type(msg).__name__ = "SystemMessage"
        assert convert_message_to_parts(msg) is None

    def test_result_message_returns_none(self):
        msg = MagicMock()
        type(msg).__name__ = "ResultMessage"
        assert convert_message_to_parts(msg) is None

    def test_assistant_message_with_content(self):
        block = MagicMock()
        block.type = "text"
        block.text = "I'll help you"

        msg = MagicMock()
        type(msg).__name__ = "AssistantMessage"
        msg.content = [block]

        parts = convert_message_to_parts(msg)
        assert parts is not None
        assert len(parts) == 1


class TestMakeMessageId:
    def test_deterministic(self):
        msg = MagicMock()
        type(msg).__name__ = "AssistantMessage"
        id1 = make_message_id(msg, 5)
        id2 = make_message_id(msg, 5)
        assert id1 == id2

    def test_different_indices(self):
        msg = MagicMock()
        type(msg).__name__ = "AssistantMessage"
        id1 = make_message_id(msg, 1)
        id2 = make_message_id(msg, 2)
        assert id1 != id2

    def test_starts_with_msg_prefix(self):
        msg = MagicMock()
        type(msg).__name__ = "AssistantMessage"
        msg_id = make_message_id(msg, 0)
        assert msg_id.startswith("msg-")


class TestStreamingEventEmitter:
    def test_deduplication(self):
        emitter = StreamingEventEmitter(task_id="task-1", context_id="ctx-1")
        assert emitter.should_emit("msg-001") is True
        assert emitter.should_emit("msg-001") is False  # already emitted
        assert emitter.should_emit("msg-002") is True

    def test_build_streaming_event(self):
        from a2a.types import Part, TextPart

        emitter = StreamingEventEmitter(task_id="task-1", context_id="ctx-1")
        parts = [Part(TextPart(text="Working..."))]
        event = emitter.build_streaming_event(
            parts=parts,
            message_id="msg-001",
            metadata={"kagent.claude.message_type": "assistant"},
        )
        assert event.task_id == "task-1"
        assert event.context_id == "ctx-1"
        assert event.final is False
        assert event.status.state.value == "working"
