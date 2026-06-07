"""Tests for ClaudeAgentExecutor."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from kagent.claude._executor import ClaudeAgentExecutor, ClaudeAgentExecutorConfig, _RunningQuery

from .conftest import MockResultMessage, MockSystemMessage, async_iter, make_executor


@pytest.mark.asyncio
async def test_execute_streams_and_completes(executor, event_queue, request_context, patch_executor_deps):
    """Successful execution emits submitted, working, artifact, completed."""
    mock_query = patch_executor_deps
    messages = [MockSystemMessage(session_id="sess-123"), MockResultMessage(result="Hello world")]
    mock_query.return_value = async_iter(messages)

    await executor.execute(request_context, event_queue)

    # Should have: submitted, working, artifact, completed = 4 events
    assert event_queue.enqueue_event.call_count == 4
    last_event = event_queue.enqueue_event.call_args_list[-1][0][0]
    assert last_event.final is True


@pytest.mark.asyncio
async def test_execute_persists_session_id(
    executor, event_queue, request_context, session_store, patch_executor_deps
):
    """Session ID from Claude SDK is stored for future turns."""
    mock_query = patch_executor_deps
    messages = [MockSystemMessage(session_id="new-sess-456"), MockResultMessage(result="Hi")]
    mock_query.return_value = async_iter(messages)

    await executor.execute(request_context, event_queue)

    assert session_store.get("test-context-id") == "new-sess-456"


@pytest.mark.asyncio
async def test_execute_resumes_with_existing_session(
    executor, event_queue, request_context, session_store, patch_executor_deps
):
    """When a session exists for the context, resume is set in options."""
    mock_query = patch_executor_deps
    session_store.set("test-context-id", "existing-sess")
    messages = [MockResultMessage(result="Resumed")]
    mock_query.return_value = async_iter(messages)

    with patch("kagent.claude._executor.ClaudeAgentOptions") as mock_opts_cls:
        mock_opts_cls.return_value = MagicMock()
        await executor.execute(request_context, event_queue)

    mock_opts_cls.assert_called_once()
    assert mock_opts_cls.call_args[1]["resume"] == "existing-sess"


@pytest.mark.asyncio
async def test_execute_handles_exception(executor, event_queue, request_context, patch_executor_deps):
    """Exception during query() emits a failed status event with classified error."""
    mock_query = patch_executor_deps

    async def _failing_iter():
        raise RuntimeError("Claude SDK error")
        yield  # noqa: unreachable — makes this an async generator

    mock_query.return_value = _failing_iter()

    await executor.execute(request_context, event_queue)

    last_event = event_queue.enqueue_event.call_args_list[-1][0][0]
    assert last_event.final is True
    assert last_event.status.state.value == "failed"
    assert last_event.metadata is not None
    assert "kagent.claude.error_type" in last_event.metadata


@pytest.mark.asyncio
async def test_execute_handles_timeout(event_queue, request_context, session_store, patch_executor_deps):
    """Timeout during query() emits a failed status event."""
    mock_query = patch_executor_deps
    executor = make_executor(session_store, execution_timeout=0.05, enable_streaming=False)

    async def _slow_iter():
        await asyncio.sleep(5.0)
        yield MockResultMessage(result="too late")

    mock_query.return_value = _slow_iter()

    await executor.execute(request_context, event_queue)

    last_event = event_queue.enqueue_event.call_args_list[-1][0][0]
    assert last_event.final is True
    assert last_event.status.state.value == "failed"
    assert last_event.metadata["kagent.claude.error_type"] == "timeout"


@pytest.mark.asyncio
async def test_cancel_raises(executor, event_queue, request_context):
    """cancel() raises NotImplementedError without side effects."""
    with pytest.raises(NotImplementedError):
        await executor.cancel(request_context, event_queue)


@pytest.mark.asyncio
async def test_shutdown_cancels_running_queries(session_store):
    """shutdown() cancels all running queries."""
    executor = make_executor(session_store)

    rq = _RunningQuery()
    rq.task = asyncio.create_task(asyncio.sleep(100))
    executor._running_queries["ctx-1"] = rq

    await executor.shutdown()
    await asyncio.sleep(0)

    assert rq.task.cancelled()
    assert "ctx-1" not in executor._running_queries


@pytest.mark.asyncio
async def test_max_concurrent_hitl_queries(event_queue, request_context, session_store, patch_executor_deps):
    """HITL execution is rejected when max concurrent queries is exceeded."""
    mock_query = patch_executor_deps
    executor = make_executor(session_store, enable_hitl=True, enable_streaming=False)

    # Fill up the running queries dict
    from kagent.claude._executor import MAX_CONCURRENT_HITL_QUERIES

    for i in range(MAX_CONCURRENT_HITL_QUERIES):
        rq = _RunningQuery()
        executor._running_queries[f"ctx-{i}"] = rq

    await executor.execute(request_context, event_queue)

    # Should emit a failed event, not start a new query
    last_event = event_queue.enqueue_event.call_args_list[-1][0][0]
    assert last_event.status.state.value == "failed"
    assert "Too many concurrent" in last_event.status.message.parts[0].root.text
