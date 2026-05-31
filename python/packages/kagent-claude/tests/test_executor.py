"""Tests for ClaudeAgentExecutor."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kagent.claude._executor import ClaudeAgentExecutor
from kagent.claude._session_store import ClaudeSessionStore


@pytest.fixture
def session_store():
    return ClaudeSessionStore()


@pytest.fixture
def executor(session_store):
    options = MagicMock()
    options.__dict__ = {"allowed_tools": ["Bash"]}
    return ClaudeAgentExecutor(
        options=options,
        session_store=session_store,
        app_name="test-agent",
    )


@pytest.fixture
def event_queue():
    queue = AsyncMock()
    queue.enqueue_event = AsyncMock()
    return queue


@pytest.fixture
def request_context():
    ctx = MagicMock()
    ctx.task_id = str(uuid.uuid4())
    ctx.context_id = "test-context-id"
    ctx.current_task = None
    ctx.message = MagicMock()
    ctx.message.parts = []
    ctx.get_user_input = MagicMock(return_value="Hello Claude")
    ctx.call_context = None
    return ctx


class MockSystemMessage:
    """Mock Claude SDK SystemMessage with init subtype."""

    def __init__(self, session_id: str):
        self.subtype = "init"
        self.data = {"session_id": session_id}


class MockResultMessage:
    """Mock Claude SDK ResultMessage with result text."""

    def __init__(self, result: str = ""):
        self.result = result


async def _async_iter(items):
    for item in items:
        yield item


@pytest.mark.asyncio
async def test_execute_streams_and_completes(executor, event_queue, request_context):
    """Successful execution emits submitted, working, artifact, completed."""
    messages = [
        MockSystemMessage(session_id="sess-123"),
        MockResultMessage(result="Hello world"),
    ]

    with patch("kagent.claude._executor.query", return_value=_async_iter(messages)):
        with patch("kagent.claude._executor.SystemMessage", MockSystemMessage):
            with patch("kagent.claude._executor.set_kagent_span_attributes", return_value=None):
                with patch("kagent.claude._executor.clear_kagent_span_attributes"):
                    await executor.execute(request_context, event_queue)

    # Should have: submitted, working, artifact, completed = 4 events
    assert event_queue.enqueue_event.call_count == 4

    # Last event should be final=True with completed state
    last_call = event_queue.enqueue_event.call_args_list[-1]
    last_event = last_call[0][0]
    assert last_event.final is True


@pytest.mark.asyncio
async def test_execute_persists_session_id(executor, event_queue, request_context, session_store):
    """Session ID from Claude SDK is stored for future turns."""
    messages = [MockSystemMessage(session_id="new-sess-456"), MockResultMessage(result="Hi")]

    with patch("kagent.claude._executor.query", return_value=_async_iter(messages)):
        with patch("kagent.claude._executor.SystemMessage", MockSystemMessage):
            with patch("kagent.claude._executor.set_kagent_span_attributes", return_value=None):
                with patch("kagent.claude._executor.clear_kagent_span_attributes"):
                    await executor.execute(request_context, event_queue)

    assert session_store.get("test-context-id") == "new-sess-456"


@pytest.mark.asyncio
async def test_execute_resumes_with_existing_session(executor, event_queue, request_context, session_store):
    """When a session exists for the context, resume is set in options."""
    session_store.set("test-context-id", "existing-sess")
    messages = [MockResultMessage(result="Resumed")]

    with patch("kagent.claude._executor.query", return_value=_async_iter(messages)) as mock_query:
        with patch("kagent.claude._executor.ClaudeAgentOptions") as mock_opts_cls:
            mock_opts_cls.return_value = MagicMock()
            with patch("kagent.claude._executor.SystemMessage", MockSystemMessage):
                with patch("kagent.claude._executor.set_kagent_span_attributes", return_value=None):
                    with patch("kagent.claude._executor.clear_kagent_span_attributes"):
                        await executor.execute(request_context, event_queue)

    # Verify ClaudeAgentOptions was called with resume
    mock_opts_cls.assert_called_once()
    call_kwargs = mock_opts_cls.call_args[1]
    assert call_kwargs["resume"] == "existing-sess"


@pytest.mark.asyncio
async def test_execute_handles_exception(executor, event_queue, request_context):
    """Exception during query() emits a failed status event."""

    async def _failing_iter():
        raise RuntimeError("Claude SDK error")
        yield  # noqa: unreachable — makes this an async generator

    with patch("kagent.claude._executor.query", return_value=_failing_iter()):
        with patch("kagent.claude._executor.SystemMessage", MockSystemMessage):
            with patch("kagent.claude._executor.set_kagent_span_attributes", return_value=None):
                with patch("kagent.claude._executor.clear_kagent_span_attributes"):
                    await executor.execute(request_context, event_queue)

    # Last event should be failed
    last_call = event_queue.enqueue_event.call_args_list[-1]
    last_event = last_call[0][0]
    assert last_event.final is True
    assert last_event.status.state.value == "failed"


@pytest.mark.asyncio
async def test_cancel_raises(executor, event_queue, request_context):
    """cancel() raises NotImplementedError."""
    with pytest.raises(NotImplementedError):
        await executor.cancel(request_context, event_queue)
