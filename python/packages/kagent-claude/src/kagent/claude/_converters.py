"""
Convert Claude Agent SDK messages to A2A DataParts for streaming intermediate events.

The Claude Agent SDK yields several message types during execution:
- SystemMessage (subtype="init") — session initialization
- AssistantMessage — Claude's thinking/response with content blocks
- ToolUseBlock (in AssistantMessage.content) — tool invocation
- ToolResultBlock (in UserMessage/ResultMessage) — tool result
- ResultMessage — final aggregated result

This module converts these into structured A2A DataParts so the kagent
dashboard can display real-time agent activity.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from a2a.types import DataPart, Message, Part, Role, TaskStatusUpdateEvent, TaskState, TaskStatus, TextPart
from kagent.core.a2a import (
    A2A_DATA_PART_METADATA_IS_LONG_RUNNING_KEY,
    A2A_DATA_PART_METADATA_TYPE_FUNCTION_CALL,
    A2A_DATA_PART_METADATA_TYPE_KEY,
    get_kagent_metadata_key,
)

logger = logging.getLogger(__name__)

# Metadata type for tool results (matching langgraph's convention)
A2A_DATA_PART_METADATA_TYPE_FUNCTION_RESPONSE = "function_response"


def convert_assistant_message(message) -> list[Part] | None:
    """
    Convert an AssistantMessage to A2A Parts.

    AssistantMessage has a .content list with TextBlock and ToolUseBlock items.
    Returns Parts for streaming to the dashboard, or None if nothing useful.
    """
    content = getattr(message, "content", None)
    if not content:
        return None

    parts: list[Part] = []

    for block in content:
        block_type = getattr(block, "type", None)

        if block_type == "tool_use":
            # Tool invocation — emit as a DataPart with function_call metadata
            tool_name = getattr(block, "name", "unknown_tool")
            tool_input = getattr(block, "input", {})
            tool_id = getattr(block, "id", "")

            data_part = DataPart(
                data={
                    "id": tool_id,
                    "name": tool_name,
                    "args": tool_input,
                },
                metadata={
                    get_kagent_metadata_key(A2A_DATA_PART_METADATA_TYPE_KEY): A2A_DATA_PART_METADATA_TYPE_FUNCTION_CALL,
                },
            )
            parts.append(Part(data_part))

        elif block_type == "text" or (hasattr(block, "text") and isinstance(getattr(block, "text", None), str)):
            text = getattr(block, "text", "")
            if text:
                parts.append(Part(TextPart(text=text)))

    return parts if parts else None


def convert_tool_result_message(message) -> list[Part] | None:
    """
    Convert a tool result message to A2A Parts.

    In the Claude Agent SDK, tool results appear as content blocks with
    type="tool_result" containing the output.
    """
    content = getattr(message, "content", None)
    if not content:
        return None

    parts: list[Part] = []

    for block in content:
        block_type = getattr(block, "type", None)

        if block_type == "tool_result":
            tool_use_id = getattr(block, "tool_use_id", "")
            tool_name = getattr(block, "name", None) or "tool_result"
            result_content = getattr(block, "content", "")

            # Result content can be a string or a list of content blocks
            if isinstance(result_content, list):
                text_parts = []
                for sub in result_content:
                    if hasattr(sub, "text"):
                        text_parts.append(sub.text)
                result_text = "\n".join(text_parts)
            else:
                result_text = str(result_content) if result_content else ""

            # Truncate very long results for the dashboard
            display_text = result_text[:2000] + "..." if len(result_text) > 2000 else result_text

            data_part = DataPart(
                data={
                    "id": tool_use_id,
                    "name": tool_name,
                    "response": {"result": display_text},
                },
                metadata={
                    get_kagent_metadata_key(A2A_DATA_PART_METADATA_TYPE_KEY): A2A_DATA_PART_METADATA_TYPE_FUNCTION_RESPONSE,
                },
            )
            parts.append(Part(data_part))

    return parts if parts else None


def classify_sdk_message(message) -> str:
    """
    Classify a Claude Agent SDK message by type.

    Returns one of: "system", "assistant", "user", "result", "unknown"
    """
    type_name = type(message).__name__

    if type_name == "SystemMessage":
        return "system"
    elif type_name == "AssistantMessage":
        return "assistant"
    elif type_name == "UserMessage":
        return "user"
    elif type_name == "ResultMessage":
        return "result"
    else:
        return "unknown"


def convert_message_to_parts(message) -> list[Part] | None:
    """
    Convert any Claude Agent SDK message to A2A Parts for streaming.

    Returns None if the message shouldn't be streamed (e.g., system init,
    final result which is handled separately).
    """
    msg_type = classify_sdk_message(message)

    if msg_type == "assistant":
        return convert_assistant_message(message)
    elif msg_type == "user":
        # User messages in the SDK are typically tool results
        return convert_tool_result_message(message)
    elif msg_type == "system":
        # System messages (init, etc.) — don't stream
        return None
    elif msg_type == "result":
        # Final result — handled by the main executor flow
        return None
    else:
        return None


def make_message_id(message, index: int) -> str:
    """Generate a deterministic message ID for deduplication."""
    # Use message type + index for a stable ID
    type_name = type(message).__name__
    content_hash = hashlib.md5(
        f"{type_name}:{index}".encode(), usedforsecurity=False
    ).hexdigest()[:12]
    return f"msg-{content_hash}"


class StreamingEventEmitter:
    """
    Manages streaming of intermediate events to the A2A event queue.

    Handles deduplication (won't re-emit the same message) and provides
    a clean interface for the executor to stream events.
    """

    def __init__(self, task_id: str, context_id: str):
        self.task_id = task_id
        self.context_id = context_id
        self._sent_ids: set[str] = set()

    def should_emit(self, message_id: str) -> bool:
        """Check if this message has already been emitted."""
        if message_id in self._sent_ids:
            return False
        self._sent_ids.add(message_id)
        return True

    def build_streaming_event(
        self,
        parts: list[Part],
        message_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> TaskStatusUpdateEvent:
        """Build a TaskStatusUpdateEvent for streaming intermediate progress."""
        return TaskStatusUpdateEvent(
            task_id=self.task_id,
            status=TaskStatus(
                state=TaskState.working,
                timestamp=datetime.now(timezone.utc).isoformat(),
                message=Message(
                    message_id=message_id,
                    role=Role.agent,
                    parts=parts,
                ),
            ),
            context_id=self.context_id,
            final=False,
            metadata=metadata,
        )
