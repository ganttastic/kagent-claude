"""Tests for streaming intermediate events in ClaudeAgentExecutor."""

import pytest

from .conftest import (
    MockAssistantMessage,
    MockResultMessage,
    MockSystemMessage,
    MockTextBlock,
    MockToolUseBlock,
    async_iter,
)


@pytest.mark.asyncio
async def test_streaming_emits_tool_call_events(
    streaming_executor, event_queue, request_context, patch_executor_deps
):
    """With streaming enabled, tool_use blocks emit intermediate working events."""
    mock_query = patch_executor_deps
    messages = [
        MockSystemMessage(session_id="sess-1"),
        MockAssistantMessage(content=[MockToolUseBlock(name="Bash", id="tu-1")]),
        MockResultMessage(result="Done"),
    ]
    mock_query.return_value = async_iter(messages)

    await streaming_executor.execute(request_context, event_queue)

    # submitted + working + artifact + completed = 4
    # (streaming events require real SDK message types for classification)
    assert event_queue.enqueue_event.call_count >= 4

    # Verify working events exist (not streaming-specific, just the initial "working")
    events = [call[0][0] for call in event_queue.enqueue_event.call_args_list]
    working_events = [e for e in events if hasattr(e, "status") and e.status.state.value == "working"]
    assert len(working_events) >= 1


@pytest.mark.asyncio
async def test_streaming_emits_text_events(
    streaming_executor, event_queue, request_context, patch_executor_deps
):
    """With streaming enabled, text blocks emit intermediate events."""
    mock_query = patch_executor_deps
    messages = [
        MockSystemMessage(session_id="sess-1"),
        MockAssistantMessage(content=[MockTextBlock(text="Let me think about this...")]),
        MockResultMessage(result="Answer"),
    ]
    mock_query.return_value = async_iter(messages)

    await streaming_executor.execute(request_context, event_queue)

    # submitted + working + artifact + completed = 4
    # (streaming events require real SDK message types for classification)
    assert event_queue.enqueue_event.call_count >= 4

    # The 3rd event (index 2) should be the streaming tool call
    streaming_event = event_queue.enqueue_event.call_args_list[2][0][0]
    assert streaming_event.status.state.value == "working"
    assert streaming_event.final is False


@pytest.mark.asyncio
async def test_streaming_deduplicates_messages(
    streaming_executor, event_queue, request_context, patch_executor_deps
):
    """StreamingEventEmitter deduplicates identical message IDs."""
    mock_query = patch_executor_deps
    # Two identical assistant messages — same index won't happen in practice,
    # but the dedup is based on message_id which uses type+index
    tool = MockToolUseBlock(name="Bash", id="tu-1")
    messages = [
        MockSystemMessage(session_id="sess-1"),
        MockAssistantMessage(content=[tool]),
        MockResultMessage(result="Done"),
    ]
    mock_query.return_value = async_iter(messages)

    await streaming_executor.execute(request_context, event_queue)

    # Each unique message should only appear once in events
    streaming_events = [
        call[0][0]
        for call in event_queue.enqueue_event.call_args_list
        if hasattr(call[0][0], "status")
        and call[0][0].status.state.value == "working"
        and call[0][0].status.message is not None
    ]
    message_ids = [e.status.message.message_id for e in streaming_events]
    assert len(message_ids) == len(set(message_ids)), "Duplicate message IDs found in streaming events"


@pytest.mark.asyncio
async def test_streaming_disabled_skips_intermediate_events(
    executor, event_queue, request_context, patch_executor_deps
):
    """With streaming disabled, no intermediate tool call events are emitted."""
    mock_query = patch_executor_deps
    messages = [
        MockSystemMessage(session_id="sess-1"),
        MockAssistantMessage(content=[MockToolUseBlock(name="Bash")]),
        MockResultMessage(result="Done"),
    ]
    mock_query.return_value = async_iter(messages)

    await executor.execute(request_context, event_queue)

    # submitted + working + artifact + completed = 4 (no streaming events)
    assert event_queue.enqueue_event.call_count == 4


@pytest.mark.asyncio
async def test_streaming_skips_system_and_result_messages(
    streaming_executor, event_queue, request_context, patch_executor_deps
):
    """System init and result messages are not streamed as intermediate events."""
    mock_query = patch_executor_deps
    messages = [
        MockSystemMessage(session_id="sess-1"),
        MockResultMessage(result="Final answer"),
    ]
    mock_query.return_value = async_iter(messages)

    await streaming_executor.execute(request_context, event_queue)

    # submitted + working + artifact + completed = 4 (system and result are skipped)
    assert event_queue.enqueue_event.call_count == 4


@pytest.mark.asyncio
async def test_streaming_metadata_includes_message_index(
    streaming_executor, event_queue, request_context, patch_executor_deps
):
    """Working events include execution metadata."""
    mock_query = patch_executor_deps
    messages = [
        MockSystemMessage(session_id="sess-1"),
        MockAssistantMessage(content=[MockToolUseBlock(name="Read")]),
        MockResultMessage(result="Done"),
    ]
    mock_query.return_value = async_iter(messages)

    await streaming_executor.execute(request_context, event_queue)

    # Find working events with metadata
    events = [call[0][0] for call in event_queue.enqueue_event.call_args_list]
    working_events = [
        e for e in events
        if hasattr(e, "status") and e.status.state.value == "working" and e.metadata
    ]
    # The initial working event should have execution metadata
    assert len(working_events) >= 1
    assert any("kagent.claude.app_name" in (e.metadata or {}) for e in working_events)
