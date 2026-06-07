"""ClaudeAgentExecutor — bridges the Claude Agent SDK to the A2A AgentExecutor interface."""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from typing import override
except ImportError:
    from typing_extensions import override

from a2a.server.agent_execution import AgentExecutor
from a2a.server.agent_execution.context import RequestContext
from a2a.server.events.event_queue import EventQueue
from a2a.types import (
    Artifact,
    DataPart,
    Message,
    Part,
    Role,
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
    TextPart,
)
from claude_agent_sdk import ClaudeAgentOptions, SystemMessage, query
from claude_agent_sdk.types import HookMatcher

from kagent.core.a2a import (
    KAGENT_HITL_DECISION_TYPE_APPROVE,
    KAGENT_HITL_DECISION_TYPE_BATCH,
    KAGENT_HITL_DECISION_TYPE_REJECT,
)
from kagent.core.tracing._span_processor import (
    clear_kagent_span_attributes,
    set_kagent_span_attributes,
)

from ._converters import (
    StreamingEventEmitter,
    classify_sdk_message,
    convert_message_to_parts,
    make_message_id,
)
from ._error_mappings import ClassifiedError, classify_error
from ._hitl import (
    ApprovalDecision,
    HitlBridge,
    build_confirmation_data_part,
    build_confirmation_metadata,
    extract_ask_user_answers_text,
    extract_hitl_decision_from_message,
)
from ._metadata_utils import (
    completion_metadata,
    error_metadata,
    execution_metadata,
    streaming_metadata,
)
from ._session_store import SessionStore
from ._tracing import record_completion, record_message_event, trace_query

logger = logging.getLogger(__name__)

# Default execution timeout (seconds) — matches reference adapters
DEFAULT_EXECUTION_TIMEOUT = 300.0

# Maximum concurrent HITL queries per executor instance.
# Prevents unbounded memory growth from unresolved HITL requests.
MAX_CONCURRENT_HITL_QUERIES = 100


@dataclass
class ClaudeAgentExecutorConfig:
    """
    Runtime behavior configuration for the Claude executor.

    Controls how the executor runs queries, reports progress, and handles
    failure modes. Pass to KAgentApp via the `executor_config` parameter.

    Example:
        config = ClaudeAgentExecutorConfig(
            execution_timeout=600.0,   # 10 minutes for long tasks
            enable_streaming=True,     # show tool calls in dashboard
            enable_hitl=True,          # require approval for tool use
        )
        app = KAgentApp(..., executor_config=config)
    """

    execution_timeout: float = DEFAULT_EXECUTION_TIMEOUT
    """Maximum seconds a query can run before being killed. Default: 300 (5 min).
    Set higher for complex coding tasks. Set lower for simple Q&A agents."""

    enable_streaming: bool = True
    """Stream intermediate events (tool calls, tool results) to the kagent
    dashboard in real-time. Disable if you only want final results."""

    enable_hitl: bool = False
    """Enable Human-in-the-Loop approval for tool use. When enabled, tools
    not in allowed_tools trigger an approval request in the dashboard.
    The user can approve, deny, or modify tool inputs before execution."""


@dataclass
class _RequestRef:
    """Atomic reference to the current request's event queue and context.

    Swapped as a single object on HITL resume so the background query
    task always sees a consistent pair — no race between two separate
    attribute mutations.
    """

    event_queue: EventQueue
    context: RequestContext


class _RunningQuery:
    """Tracks a background Claude query that may be paused for HITL."""

    def __init__(self):
        self.task: asyncio.Task | None = None
        self.hitl_event: asyncio.Event = asyncio.Event()
        self.completed_event: asyncio.Event = asyncio.Event()
        self.result_text: str = ""
        self.session_id: str | None = None
        self.error: Exception | None = None
        # Atomic reference to the current request — swapped on HITL resume.
        # The background task reads this; the resume path replaces it.
        self.request_ref: _RequestRef | None = None
        # Accumulated tool call parts for the final artifact
        self.tool_parts: list[Part] = []


class ClaudeAgentExecutor(AgentExecutor):
    """
    Bridges the Claude Agent SDK to the A2A AgentExecutor interface.

    Features:
    - Streaming intermediate events (tool calls, results) to the dashboard
    - Execution timeout with configurable duration
    - Error classification with user-friendly messages
    - HITL (Human-in-the-Loop) via PreToolUse hooks that pause for user approval
    - Session continuity via session_id resume
    - OpenTelemetry tracing integration
    """

    def __init__(
        self,
        *,
        options: ClaudeAgentOptions,
        session_store: SessionStore,
        app_name: str = "kagent-claude",
        config: ClaudeAgentExecutorConfig | None = None,
    ):
        super().__init__()
        self.options = options
        self.session_store: SessionStore = session_store
        self.app_name = app_name
        self._config = config or ClaudeAgentExecutorConfig()

        self._hitl_bridge = HitlBridge()
        # context_id -> running query (for HITL resume)
        self._running_queries: dict[str, _RunningQuery] = {}

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError(
            "Cancellation is not supported by the Claude Agent SDK. "
            "Use shutdown() for graceful cleanup of all running queries."
        )

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        if not context.message:
            raise ValueError("A2A request must have a message")

        context_id = context.context_id

        # Check if this is a resume (HITL response)
        if self._is_hitl_resume(context):
            await self._handle_hitl_resume(context, event_queue)
            return

        # Check if this is an ask-user answer (user responding to a question from Claude)
        ask_user_text = extract_ask_user_answers_text(context.message)

        span_attributes = _build_span_attributes(context)
        context_token = set_kagent_span_attributes(span_attributes)
        try:
            # Extract user input — prefer ask-user answer if present
            if ask_user_text:
                user_input = ask_user_text
            else:
                user_input = context.get_user_input()
                if not user_input:
                    user_input = _extract_text(context.message)

            # Look up existing Claude session for this context
            claude_session_id = self.session_store.get(context_id) if context_id else None

            # Build options
            options = self._build_options(claude_session_id, context_id)

            # Signal submitted state if new task
            if not context.current_task:
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        task_id=context.task_id,
                        status=TaskStatus(
                            state=TaskState.submitted,
                            message=context.message,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        ),
                        context_id=context.context_id,
                        final=False,
                    )
                )

            # Signal working state with rich metadata
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    status=TaskStatus(
                        state=TaskState.working,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ),
                    context_id=context.context_id,
                    final=False,
                    metadata=execution_metadata(
                        app_name=self.app_name,
                        session_id=context.context_id,
                        claude_session_id=claude_session_id,
                        is_resume=claude_session_id is not None,
                    ),
                )
            )

            if self._config.enable_hitl:
                await self._execute_with_hitl(
                    user_input, options, claude_session_id, context, event_queue
                )
            else:
                await self._execute_simple(
                    user_input, options, claude_session_id, context, event_queue
                )
        finally:
            clear_kagent_span_attributes(context_token)

    async def _execute_simple(
        self,
        user_input: str,
        options: ClaudeAgentOptions,
        claude_session_id: str | None,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Execute without HITL — streaming to completion with timeout."""
        start_time = time.monotonic()

        try:
            await asyncio.wait_for(
                self._run_query_streaming(
                    user_input, options, claude_session_id, context, event_queue
                ),
                timeout=self._config.execution_timeout,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start_time
            classified = classify_error(asyncio.TimeoutError(
                f"Execution timed out after {elapsed:.1f}s "
                f"(limit: {self._config.execution_timeout}s)"
            ))
            await self._emit_failed_classified(context, event_queue, classified)
        except asyncio.CancelledError:
            classified = classify_error(asyncio.CancelledError())
            await self._emit_failed_classified(context, event_queue, classified)
        except Exception as e:
            classified = classify_error(e)
            logger.error(
                f"Claude Agent SDK execution failed: {classified.error_type}: {e}",
                exc_info=True,
            )
            await self._emit_failed_classified(context, event_queue, classified)

    async def _run_query_streaming(
        self,
        user_input: str,
        options: ClaudeAgentOptions,
        claude_session_id: str | None,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Core query loop with streaming intermediate events."""
        context_id = context.context_id
        accumulated_text: list[str] = []
        new_session_id: str | None = None
        msg_index = 0
        start_time = time.monotonic()

        # Streaming event emitter for deduplication
        emitter = StreamingEventEmitter(
            task_id=context.task_id,
            context_id=context_id,
        )

        async with trace_query(
            prompt=user_input,
            session_id=claude_session_id,
            context_id=context_id,
            app_name=self.app_name,
        ) as span:
            async for message in query(
                prompt=user_input,
                options=options,
            ):
                record_message_event(span, message, msg_index)
                msg_index += 1

                # Capture session ID from init message
                if (
                    new_session_id is None
                    and isinstance(message, SystemMessage)
                    and getattr(message, "subtype", None) == "init"
                    and hasattr(message, "data")
                    and isinstance(message.data, dict)
                ):
                    new_session_id = message.data.get("session_id")

                # Stream intermediate events to dashboard
                if self._config.enable_streaming:
                    await self._stream_intermediate_event(
                        message, msg_index, emitter, event_queue
                    )

                # Capture final result text
                if hasattr(message, "result") and message.result:
                    accumulated_text.append(message.result)

            final_text = "".join(accumulated_text) or "No response was generated."
            record_completion(span, new_session_id, msg_index, len(final_text))

        # Persist session mapping
        if new_session_id and context_id:
            self.session_store.set(context_id, new_session_id)

        # Emit completion with rich metadata
        duration_ms = (time.monotonic() - start_time) * 1000
        await self._emit_completed(
            context, event_queue, final_text,
            metadata=completion_metadata(
                session_id=context_id,
                claude_session_id=new_session_id,
                message_count=msg_index,
                result_length=len(final_text),
                duration_ms=duration_ms,
            ),
        )

    async def _stream_intermediate_event(
        self,
        message,
        msg_index: int,
        emitter: StreamingEventEmitter,
        event_queue: EventQueue,
    ) -> None:
        """Convert and stream a single SDK message as an A2A event."""
        # Don't stream system init or final result messages
        msg_type = classify_sdk_message(message)
        if msg_type in ("system", "result"):
            return

        parts = convert_message_to_parts(message)
        if not parts:
            return

        message_id = make_message_id(message, msg_index)
        if not emitter.should_emit(message_id):
            return

        # Extract tool name for metadata (if it's a tool call)
        tool_name = None
        for part in parts:
            part_inner = part.root if hasattr(part, "root") else part
            if isinstance(part_inner, DataPart) and isinstance(part_inner.data, dict):
                tool_name = part_inner.data.get("name")
                break

        event = emitter.build_streaming_event(
            parts=parts,
            message_id=message_id,
            metadata=streaming_metadata(
                message_index=msg_index,
                message_type=msg_type,
                tool_name=tool_name,
            ),
        )
        await event_queue.enqueue_event(event)

    async def _execute_with_hitl(
        self,
        user_input: str,
        options: ClaudeAgentOptions,
        claude_session_id: str | None,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """
        Execute with HITL support via PreToolUse hooks.

        Uses a PreToolUse hook that pauses Claude's execution by awaiting
        a Future on the HITL bridge. When the user approves/denies via the
        kagent dashboard, the bridge resolves the Future and the hook returns
        the decision to the SDK.
        """
        context_id = context.context_id

        # SEC-4: Guard against unbounded concurrent HITL queries
        if len(self._running_queries) >= MAX_CONCURRENT_HITL_QUERIES:
            await self._emit_failed(
                context, event_queue,
                f"Too many concurrent HITL queries (limit: {MAX_CONCURRENT_HITL_QUERIES}). "
                "Please resolve or cancel pending approvals before starting new queries.",
            )
            return

        rq = _RunningQuery()
        rq.request_ref = _RequestRef(event_queue=event_queue, context=context)
        self._running_queries[context_id] = rq

        # Register the HITL notify event so the bridge can wake us without polling
        self._hitl_bridge.register_notify_event(context_id, rq.hitl_event)

        # Inject PreToolUse hook that pauses for HITL approval
        hitl_options = self._inject_hitl_options(options, context_id)

        async def _run_query():
            """Background coroutine that runs the Claude query to completion."""
            accumulated_text: list[str] = []
            new_session_id: str | None = None

            try:
                async for message in query(
                    prompt=user_input,
                    options=hitl_options,
                ):
                    if (
                        new_session_id is None
                        and isinstance(message, SystemMessage)
                        and getattr(message, "subtype", None) == "init"
                        and hasattr(message, "data")
                        and isinstance(message.data, dict)
                    ):
                        new_session_id = message.data.get("session_id")

                    if hasattr(message, "result") and message.result:
                        accumulated_text.append(message.result)

                rq.result_text = "".join(accumulated_text) or "No response was generated."
                rq.session_id = new_session_id
            except asyncio.CancelledError:
                raise
            except Exception as e:
                rq.error = e
            finally:
                rq.completed_event.set()

        # Start the background query
        rq.task = asyncio.create_task(_run_query())

        # Wait for either: completion OR an HITL approval request
        try:
            await asyncio.wait_for(
                self._wait_for_hitl_or_completion(context_id, rq, context, event_queue),
                timeout=self._config.execution_timeout,
            )
        except asyncio.TimeoutError:
            # Cancel the background query
            if rq.task and not rq.task.done():
                rq.task.cancel()
            self._running_queries.pop(context_id, None)
            self._hitl_bridge.cancel_all(context_id)
            classified = classify_error(asyncio.TimeoutError(
                f"Execution timed out after {self._config.execution_timeout}s"
            ))
            await self._emit_failed_classified(context, event_queue, classified)

    async def _wait_for_hitl_or_completion(
        self,
        context_id: str,
        rq: _RunningQuery,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Wait until the query completes or HITL input is needed.

        Uses ``asyncio.wait()`` on the background task and the HITL notify
        event instead of polling, so we wake up only when something actually
        happens.
        """

        async def _wait_for_hitl():
            """Coroutine that completes when the HITL bridge needs input."""
            await rq.hitl_event.wait()

        hitl_waiter = asyncio.ensure_future(_wait_for_hitl())
        try:
            # Wait for whichever fires first: query done or HITL needed
            logger.debug(f"HITL wait: task.done={rq.task.done()}, hitl_event.is_set={rq.hitl_event.is_set()}")
            done, _pending = await asyncio.wait(
                [rq.task, hitl_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )

            if hitl_waiter in done:
                # Claude is paused waiting for approval — emit input_required
                logger.info(f"HITL: tool approval needed for context {context_id}")
                await self._emit_input_required(context, event_queue)
                # Reset the event for the next round of HITL
                rq.hitl_event.clear()
                # Return control — the next execute() call will resume
                return

            # The query task finished (hitl_waiter was not in done)
            logger.info(f"HITL: query completed for context {context_id}")
            # Ensure completed_event is set so callers see it
            rq.completed_event.set()
        finally:
            # Clean up the hitl_waiter if it's still pending
            if not hitl_waiter.done():
                hitl_waiter.cancel()
                try:
                    await hitl_waiter
                except asyncio.CancelledError:
                    pass

        # Query completed without HITL interruption
        self._running_queries.pop(context_id, None)
        self._hitl_bridge.unregister_notify_event(context_id)

        if rq.error:
            classified = classify_error(rq.error)
            await self._emit_failed_classified(context, event_queue, classified)
        else:
            if rq.session_id and context_id:
                self.session_store.set(context_id, rq.session_id)
            await self._emit_completed(
                context, event_queue, rq.result_text, tool_parts=rq.tool_parts
            )

    def _is_hitl_resume(self, context: RequestContext) -> bool:
        """Check if this execute() call is a HITL response to a pending approval."""
        context_id = context.context_id
        if not context_id:
            return False
        if not self._hitl_bridge.has_pending(context_id):
            return False
        # Check if the message contains a decision (using kagent-core utilities)
        return extract_hitl_decision_from_message(context.message) is not None

    async def _handle_hitl_resume(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Handle a HITL resume: resolve pending approvals and wait for completion."""
        context_id = context.context_id
        logger.info(f"HITL resume for context {context_id}")
        result = extract_hitl_decision_from_message(context.message)
        if not result:
            logger.warning(f"HITL resume: invalid message for context {context_id}")
            await self._emit_failed(context, event_queue, "Invalid HITL response message")
            return

        decision_type, decisions, rejection_reasons = result
        logger.info(f"HITL resume: decision_type={decision_type} for context {context_id}")

        # Resolve the pending approvals using kagent-core constants
        if decision_type == KAGENT_HITL_DECISION_TYPE_BATCH:
            self._hitl_bridge.resolve_batch(context_id, decisions, rejection_reasons)
        elif decision_type == KAGENT_HITL_DECISION_TYPE_APPROVE:
            self._hitl_bridge.resolve_all(
                context_id, ApprovalDecision(approved=True)
            )
        elif decision_type == KAGENT_HITL_DECISION_TYPE_REJECT:
            reason = rejection_reasons.get("__all__", "User rejected this action")
            self._hitl_bridge.resolve_all(
                context_id, ApprovalDecision(approved=False, rejection_reason=reason)
            )

        # Do NOT emit a "working" event here — the a2a framework's
        # consume_and_break_on_interrupt returns the HTTP response on
        # any non-final event. We need the queue to stay open until we
        # emit either input_required (another tool) or completed/failed.

        # Wait for the background query to either complete or hit another HITL
        rq = self._running_queries.get(context_id)
        if not rq:
            await self._emit_failed(context, event_queue, "No running query to resume")
            return

        # Atomically swap the request reference for this resume —
        # the background task reads rq.request_ref as a single object.
        rq.request_ref = _RequestRef(event_queue=event_queue, context=context)

        # Clear the HITL event before re-entering the wait loop.
        # The event was set by the bridge when the approval was created;
        # now that we've resolved it, we need a fresh event for the next tool.
        rq.hitl_event.clear()

        try:
            await asyncio.wait_for(
                self._wait_for_hitl_or_completion(context_id, rq, context, event_queue),
                timeout=self._config.execution_timeout,
            )
        except asyncio.TimeoutError:
            if rq.task and not rq.task.done():
                rq.task.cancel()
            self._running_queries.pop(context_id, None)
            self._hitl_bridge.cancel_all(context_id)
            classified = classify_error(asyncio.TimeoutError("HITL resume timed out"))
            await self._emit_failed_classified(context, event_queue, classified)

    async def _emit_input_required(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Emit input_required with tool approval DataParts."""
        context_id = context.context_id
        pending = self._hitl_bridge.get_pending(context_id)

        parts: list[Part] = []
        for approval in pending:
            parts.append(
                Part(
                    DataPart(
                        data=build_confirmation_data_part(approval),
                        metadata=build_confirmation_metadata(),
                    )
                )
            )

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(
                    state=TaskState.input_required,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        role=Role.agent,
                        parts=parts,
                    ),
                ),
                context_id=context.context_id,
                final=False,
            )
        )

    async def _emit_completed(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        text: str,
        metadata: dict[str, Any] | None = None,
        tool_parts: list[Part] | None = None,
    ) -> None:
        """Emit artifact + completed status.

        The artifact includes tool call/result DataParts (if any) followed
        by the final text. This enables the dashboard to show the full turn
        history on page refresh.
        """
        # Build artifact parts: tool history + final text
        parts: list[Part] = []
        if tool_parts:
            parts.extend(tool_parts)
        parts.append(Part(TextPart(text=text)))

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                last_chunk=True,
                context_id=context.context_id,
                artifact=Artifact(
                    artifact_id=str(uuid.uuid4()),
                    parts=parts,
                ),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(
                    state=TaskState.completed,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
                context_id=context.context_id,
                final=True,
                metadata=metadata,
            )
        )

    async def _emit_failed(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        error_msg: str,
    ) -> None:
        """Emit failed status with raw error message (legacy)."""
        logger.error(f"Claude Agent SDK execution failed: {error_msg}")
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(
                    state=TaskState.failed,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        role=Role.agent,
                        parts=[Part(TextPart(text=error_msg))],
                    ),
                ),
                context_id=context.context_id,
                final=True,
            )
        )

    async def _emit_failed_classified(
        self,
        context: RequestContext,
        event_queue: EventQueue,
        classified: ClassifiedError,
    ) -> None:
        """Emit failed status with classified error and structured metadata."""
        logger.error(
            f"Claude Agent SDK execution failed [{classified.error_type}]: "
            f"{classified.detail}"
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(
                    state=TaskState.failed,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    message=Message(
                        message_id=str(uuid.uuid4()),
                        role=Role.agent,
                        parts=[Part(TextPart(text=classified.user_message))],
                    ),
                ),
                context_id=context.context_id,
                final=True,
                metadata=error_metadata(
                    error_type=classified.error_type,
                    error_detail=classified.detail,
                    is_transient=classified.is_transient,
                ),
            )
        )

    def _build_options(
        self, claude_session_id: str | None, context_id: str | None
    ) -> ClaudeAgentOptions:
        """Build ClaudeAgentOptions, injecting resume if resuming a session."""
        if claude_session_id:
            return ClaudeAgentOptions(
                **_public_attrs(self.options),
                resume=claude_session_id,
            )
        return self.options

    def _inject_hitl_options(
        self, options: ClaudeAgentOptions, context_id: str
    ) -> ClaudeAgentOptions:
        """
        Inject a PreToolUse hook that pauses execution for HITL approval.

        The hook creates a pending approval on the bridge, awaits the user's
        decision Future, and returns {"decision": "approve"} or
        {"decision": "block", "reason": "..."} to the SDK.

        Tools already in ``allowed_tools`` are auto-approved (no prompt).
        Only tools NOT in the allowed list trigger the approval flow.
        """
        bridge = self._hitl_bridge
        running_queries = self._running_queries
        # Build the set of pre-approved tools for fast lookup
        allowed = set(getattr(options, "allowed_tools", None) or [])

        async def _hitl_pre_tool_use(input_data, tool_use_id, hook_context):
            tool_name = input_data.get("tool_name", "unknown")
            tool_input = input_data.get("tool_input", {})

            # Auto-approve tools that are already in allowed_tools
            if tool_name in allowed:
                logger.debug(f"HITL: auto-approving pre-approved tool {tool_name}")
                # Build the tool call part
                tool_call_part = Part(DataPart(
                    data={
                        "id": tool_use_id,
                        "name": tool_name,
                        "args": tool_input,
                    },
                    metadata={
                        "kagent_type": "function_call",
                    },
                ))
                # Accumulate for final artifact
                rq = running_queries.get(context_id)
                if rq:
                    rq.tool_parts.append(tool_call_part)
                    # Emit informational tool call event to the dashboard
                    ref = rq.request_ref
                    if ref:
                        try:
                            event = TaskStatusUpdateEvent(
                                task_id=ref.context.task_id,
                                status=TaskStatus(
                                    state=TaskState.working,
                                    timestamp=datetime.now(timezone.utc).isoformat(),
                                    message=Message(
                                        message_id=str(uuid.uuid4()),
                                        role=Role.agent,
                                        parts=[tool_call_part],
                                    ),
                                ),
                                context_id=context_id,
                                final=False,
                            )
                            await ref.event_queue.enqueue_event(event)
                        except Exception:
                            # Don't fail the tool call if event emission fails
                            pass
                return {"decision": "approve"}

            # Create approval and pause — the bridge signals the notify event
            logger.info(f"HITL: requesting approval for tool {tool_name}")
            approval = bridge.create_approval(
                context_id=context_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_use_id=tool_use_id,
            )

            # Await the user's decision (set by _handle_hitl_resume)
            decision: ApprovalDecision = await approval.future

            if decision.approved:
                return {"decision": "approve"}
            else:
                return {
                    "decision": "block",
                    "reason": decision.rejection_reason or "User denied this action",
                }

        async def _post_tool_use(input_data, tool_use_id, hook_context):
            """Emit tool result event to dashboard after tool execution."""
            tool_name = input_data.get("tool_name", "unknown")
            tool_response = input_data.get("tool_response", "")

            # Format the response for display
            if isinstance(tool_response, dict):
                response_data = tool_response
            elif isinstance(tool_response, str):
                display = tool_response[:2000] + "..." if len(tool_response) > 2000 else tool_response
                response_data = {"result": display}
            else:
                response_data = {"result": str(tool_response)[:2000]}

            tool_result_part = Part(DataPart(
                data={
                    "id": tool_use_id,
                    "name": tool_name,
                    "response": response_data,
                },
                metadata={
                    "kagent_type": "function_response",
                },
            ))

            rq = running_queries.get(context_id)
            if rq:
                rq.tool_parts.append(tool_result_part)
                ref = rq.request_ref
                if ref:
                    try:
                        event = TaskStatusUpdateEvent(
                            task_id=ref.context.task_id,
                            status=TaskStatus(
                                state=TaskState.working,
                                timestamp=datetime.now(timezone.utc).isoformat(),
                                message=Message(
                                    message_id=str(uuid.uuid4()),
                                    role=Role.agent,
                                    parts=[tool_result_part],
                                ),
                            ),
                            context_id=context_id,
                            final=False,
                        )
                        await ref.event_queue.enqueue_event(event)
                    except Exception:
                        pass
            return {}

        existing_hooks = getattr(options, "hooks", None) or {}
        pre_tool_use = existing_hooks.get("PreToolUse", [])
        pre_tool_use = list(pre_tool_use) + [
            HookMatcher(matcher=None, hooks=[_hitl_pre_tool_use])
        ]
        post_tool_use = existing_hooks.get("PostToolUse", [])
        post_tool_use = list(post_tool_use) + [
            HookMatcher(matcher=None, hooks=[_post_tool_use])
        ]
        updated_hooks = {
            **existing_hooks,
            "PreToolUse": pre_tool_use,
            "PostToolUse": post_tool_use,
        }

        # Build new options with hooks (no can_use_tool needed)
        opts_dict = _public_attrs(options)
        opts_dict["hooks"] = updated_hooks

        return ClaudeAgentOptions(**opts_dict)

    async def shutdown(self) -> None:
        """
        Graceful shutdown — cancel all running queries and clean up.

        Call this from FastAPI's lifespan or shutdown event.
        """
        logger.info("ClaudeAgentExecutor shutting down, cancelling running queries...")
        for context_id in list(self._running_queries.keys()):
            rq = self._running_queries.pop(context_id, None)
            if rq and rq.task and not rq.task.done():
                rq.task.cancel()
            self._hitl_bridge.cancel_all(context_id)
        logger.info("ClaudeAgentExecutor shutdown complete.")


def _extract_text(message) -> str:
    """Extract plain text from an A2A Message's parts."""
    parts = getattr(message, "parts", [])
    for part in parts:
        if isinstance(part, TextPart):
            return part.text
        if hasattr(part, "root") and hasattr(part.root, "text"):
            return part.root.text
        if hasattr(part, "text"):
            return part.text
    return ""


def _build_span_attributes(context: RequestContext) -> dict[str, Any]:
    """Build OpenTelemetry span attributes from the request context."""
    user_id = "admin@kagent.dev"
    if context.call_context and context.call_context.user and context.call_context.user.user_name:
        user_id = context.call_context.user.user_name

    attrs = {
        "kagent.user_id": user_id,
        "gen_ai.conversation.id": context.context_id,
    }
    if context.task_id:
        attrs["gen_ai.task.id"] = context.task_id
    return attrs


def _public_attrs(obj: object) -> dict[str, Any]:
    """Extract public (non-underscore-prefixed) attributes with non-None values.

    Used instead of raw ``obj.__dict__`` spreading to avoid leaking internal
    state when constructing new ``ClaudeAgentOptions`` instances.
    """
    return {k: v for k, v in obj.__dict__.items() if not k.startswith("_") and v is not None}
