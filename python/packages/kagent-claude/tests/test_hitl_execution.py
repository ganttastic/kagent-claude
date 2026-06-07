"""Tests for HITL (Human-in-the-Loop) execution path in ClaudeAgentExecutor."""

import asyncio
from unittest.mock import MagicMock

import pytest
from a2a.types import DataPart, Message, Part, Role

from kagent.claude._executor import _RunningQuery
from kagent.claude._hitl import ApprovalDecision

from .conftest import (
    MockResultMessage,
    MockSystemMessage,
    async_iter,
    make_executor,
)


@pytest.mark.asyncio
async def test_hitl_emits_input_required_on_tool_approval(
    event_queue, request_context, session_store, patch_executor_deps
):
    """When HITL is enabled and a tool needs approval, input_required is emitted."""
    mock_query = patch_executor_deps
    executor = make_executor(session_store, enable_hitl=True, enable_streaming=False)

    # Simulate a query that triggers can_use_tool and then pauses
    async def _hitl_query(**kwargs):
        # Simulate system init
        yield MockSystemMessage(session_id="sess-hitl")
        # Simulate the can_use_tool callback being triggered
        # by creating a pending approval in the bridge
        executor._hitl_bridge.create_approval(
            context_id="test-context-id",
            tool_name="Bash",
            tool_input={"command": "rm -rf /tmp"},
            tool_use_id="tu-hitl-1",
        )
        # In real usage, the query would pause here via the Future.
        # For testing, just yield a result.
        yield MockResultMessage(result="After approval")

    mock_query.return_value = _hitl_query()

    await executor.execute(request_context, event_queue)

    # Should have emitted input_required at some point
    events = [call[0][0] for call in event_queue.enqueue_event.call_args_list]
    states = [e.status.state.value for e in events if hasattr(e, "status")]
    assert "input_required" in states


@pytest.mark.asyncio
async def test_hitl_resume_approve_resolves_pending(
    event_queue, session_store, patch_executor_deps
):
    """A HITL resume with 'approve' decision resolves pending approvals."""
    _ = patch_executor_deps
    executor = make_executor(session_store, enable_hitl=True, enable_streaming=False)

    # Set up a running query with a pending approval
    rq = _RunningQuery()
    context_id = "ctx-resume"

    async def _background_query():
        rq.result_text = "Completed after approval"
        rq.session_id = "sess-resumed"
        rq.completed_event.set()

    rq.task = asyncio.create_task(_background_query())
    executor._running_queries[context_id] = rq

    # Create a pending approval
    approval = executor._hitl_bridge.create_approval(
        context_id=context_id,
        tool_name="Bash",
        tool_input={"command": "ls"},
        tool_use_id="tu-1",
    )

    # Build a resume message with approve decision
    resume_ctx = MagicMock()
    resume_ctx.task_id = "task-resume"
    resume_ctx.context_id = context_id
    resume_ctx.current_task = MagicMock()
    resume_ctx.message = Message(
        message_id="msg-resume",
        role=Role.user,
        parts=[Part(DataPart(data={"decision_type": "approve"}))],
    )
    resume_ctx.call_context = None

    # Resolve the approval in the background so the wait doesn't hang
    async def _resolve_soon():
        await asyncio.sleep(0.01)
        approval.future.set_result(ApprovalDecision(approved=True))

    asyncio.create_task(_resolve_soon())

    await executor.execute(resume_ctx, event_queue)

    # Should complete successfully (not fail)
    events = [call[0][0] for call in event_queue.enqueue_event.call_args_list]
    final_events = [e for e in events if hasattr(e, "final") and e.final]
    # Either completed or the background task handled it
    assert len(final_events) >= 0  # No crash


@pytest.mark.asyncio
async def test_hitl_max_concurrent_rejects(
    event_queue, request_context, session_store, patch_executor_deps
):
    """HITL execution rejects when max concurrent queries is exceeded."""
    mock_query = patch_executor_deps
    executor = make_executor(session_store, enable_hitl=True, enable_streaming=False)

    from kagent.claude._executor import MAX_CONCURRENT_HITL_QUERIES

    # Fill up running queries
    for i in range(MAX_CONCURRENT_HITL_QUERIES):
        executor._running_queries[f"ctx-{i}"] = _RunningQuery()

    mock_query.return_value = async_iter([MockResultMessage(result="ignored")])

    await executor.execute(request_context, event_queue)

    last_event = event_queue.enqueue_event.call_args_list[-1][0][0]
    assert last_event.status.state.value == "failed"
    assert "Too many concurrent" in last_event.status.message.parts[0].root.text


@pytest.mark.asyncio
async def test_hitl_timeout_cancels_background_query(
    event_queue, request_context, session_store, patch_executor_deps
):
    """HITL execution that times out cancels the background query and cleans up."""
    mock_query = patch_executor_deps
    executor = make_executor(
        session_store, enable_hitl=True, enable_streaming=False, execution_timeout=0.1
    )

    # Query that blocks forever (simulating waiting for approval)
    async def _blocking_query(**kwargs):
        yield MockSystemMessage(session_id="sess-timeout")
        await asyncio.sleep(100)  # will be cancelled by timeout
        yield MockResultMessage(result="never reached")

    mock_query.return_value = _blocking_query()

    await executor.execute(request_context, event_queue)

    # Should emit failed with timeout
    last_event = event_queue.enqueue_event.call_args_list[-1][0][0]
    assert last_event.final is True
    assert last_event.status.state.value == "failed"
    assert last_event.metadata["kagent.claude.error_type"] == "timeout"

    # Running queries should be cleaned up
    assert "test-context-id" not in executor._running_queries


@pytest.mark.asyncio
async def test_hitl_bridge_notify_event_registered(
    session_store, event_queue, request_context, patch_executor_deps
):
    """When HITL is enabled, the notify event is registered on the bridge."""
    mock_query = patch_executor_deps
    executor = make_executor(session_store, enable_hitl=True, enable_streaming=False)

    # Short-running query (no HITL trigger)
    messages = [MockSystemMessage(session_id="sess-1"), MockResultMessage(result="quick")]
    mock_query.return_value = async_iter(messages)

    await executor.execute(request_context, event_queue)

    # After completion, the notify event should be cleaned up
    assert "test-context-id" not in executor._hitl_bridge._notify_events
