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
from ._error_mappings import ClassifiedError, classify_error, get_error_metadata
from ._hitl import (
    ApprovalDecision,
    HitlBridge,
    build_confirmation_data_part,
    build_confirmation_metadata,
    extract_ask_user_answers_text,
    extract_hitl_decision_from_message,
    make_can_use_tool_callback,
)
from ._metadata_utils import (
    completion_metadata,
    error_metadata,
    execution_metadata,
    streaming_metadata,
)
from ._session_store import ClaudeSessionStore
from ._tracing import record_completion, record_message_event, trace_query

logger = logging.getLogger(__name__)

# Default execution timeout (seconds) — matches reference adapters
DEFAULT_EXECUTION_TIMEOUT = 300.0


@dataclass
class ClaudeExecutorConfig:
    """
    Runtime behavior configuration for the Claude executor.

    Controls how the executor runs queries, reports progress, and handles
    failure modes. Pass to KAgentApp via the `executor_config` parameter.

    Example:
        config = ClaudeExecutorConfig(
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


class _RunningQuery:
    """Tracks a background Claude query that may be paused for HITL."""

    def __init__(self):
        self.task: asyncio.Task | None = None
        self.hitl_event: asyncio.Event = asyncio.Event()
        self.completed_event: asyncio.Event = asyncio.Event()
        self.result_text: str = ""
        self.session_id: str | None = None
        self.error: Exception | None = None


class ClaudeAgentExecutor(AgentExecutor):
    """
    Bridges the Claude Agent SDK to the A2A AgentExecutor interface.

    Features:
    - Streaming intermediate events (tool calls, results) to the dashboard
    - Execution timeout with configurable duration
    - Error classification with user-friendly messages
    - HITL (Human-in-the-Loop) via the Claude SDK's can_use_tool callback
    - Session continuity via session_id resume
    - OpenTelemetry tracing integration
    """

    def __init__(
        self,
        *,
        options: ClaudeAgentOptions,
        session_store: ClaudeSessionStore,
        app_name: str = "kagent-claude",
        config: ClaudeExecutorConfig | None = None,
        # Legacy kwargs for backward compatibility
        enable_hitl: bool = False,
    ):
        super().__init__()
        self.options = options
        self.session_store = session_store
        self.app_name = app_name

        # Merge config with legacy kwargs
        if config:
            self._config = config
        else:
            self._config = ClaudeExecutorConfig(enable_hitl=enable_hitl)

        self._hitl_bridge = HitlBridge()
        # context_id -> running query (for HITL resume)
        self._running_queries: dict[str, _RunningQuery] = {}

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        # Cancel any running query for this context
        context_id = context.context_id
        if context_id and context_id in self._running_queries:
            rq = self._running_queries.pop(context_id)
            if rq.task and not rq.task.done():
                rq.task.cancel()
            self._hitl_bridge.cancel_all(context_id)
        raise NotImplementedError("Cancellation is not supported by the Claude Agent SDK executor.")

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
        context_id = context.context_id
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
        Execute with HITL support.

        Runs the Claude query in a background task. If can_use_tool fires,
        the bridge signals us to emit input_required and return. The background
        task stays paused until the next execute() call resolves the approval.
        """
        context_id = context.context_id
        rq = _RunningQuery()
        self._running_queries[context_id] = rq

        # Create the can_use_tool callback wired to our bridge
        can_use_tool = await make_can_use_tool_callback(self._hitl_bridge, context_id)

        # Inject can_use_tool and the required PreToolUse hook into options
        hitl_options = self._inject_hitl_options(options, can_use_tool)

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
        """Poll until query completes or HITL is needed."""
        while True:
            if rq.completed_event.is_set():
                break
            if self._hitl_bridge.has_pending(context_id):
                # Claude is paused waiting for approval — emit input_required
                await self._emit_input_required(context, event_queue)
                # Return control — the next execute() will resume
                return
            # Brief sleep to avoid busy-waiting
            await asyncio.sleep(0.05)
            if rq.task.done():
                rq.completed_event.set()
                break

        # Query completed without HITL interruption
        self._running_queries.pop(context_id, None)

        if rq.error:
            classified = classify_error(rq.error)
            await self._emit_failed_classified(context, event_queue, classified)
        else:
            if rq.session_id and context_id:
                self.session_store.set(context_id, rq.session_id)
            await self._emit_completed(context, event_queue, rq.result_text)

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
        result = extract_hitl_decision_from_message(context.message)
        if not result:
            await self._emit_failed(context, event_queue, "Invalid HITL response message")
            return

        decision_type, decisions, rejection_reasons = result

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

        # Signal working state again
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                status=TaskStatus(
                    state=TaskState.working,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ),
                context_id=context.context_id,
                final=False,
            )
        )

        # Wait for the background query to either complete or hit another HITL
        rq = self._running_queries.get(context_id)
        if not rq:
            await self._emit_failed(context, event_queue, "No running query to resume")
            return

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
    ) -> None:
        """Emit artifact + completed status."""
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=context.task_id,
                last_chunk=True,
                context_id=context.context_id,
                artifact=Artifact(
                    artifact_id=str(uuid.uuid4()),
                    parts=[Part(TextPart(text=text))],
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
                **{k: v for k, v in self.options.__dict__.items() if v is not None},
                resume=claude_session_id,
            )
        return self.options

    def _inject_hitl_options(
        self, options: ClaudeAgentOptions, can_use_tool
    ) -> ClaudeAgentOptions:
        """
        Inject can_use_tool callback and the required PreToolUse dummy hook
        into the options for HITL mode.
        """
        # The Claude SDK requires a PreToolUse hook returning {"continue_": True}
        # to keep the stream open while can_use_tool is pending
        async def _keep_stream_open(input_data, tool_use_id, context):
            return {"continue_": True}

        existing_hooks = getattr(options, "hooks", None) or {}
        pre_tool_use = existing_hooks.get("PreToolUse", [])
        pre_tool_use = list(pre_tool_use) + [
            HookMatcher(matcher=None, hooks=[_keep_stream_open])
        ]
        updated_hooks = {**existing_hooks, "PreToolUse": pre_tool_use}

        # Build new options with can_use_tool and hooks
        opts_dict = {k: v for k, v in options.__dict__.items() if v is not None}
        opts_dict["can_use_tool"] = can_use_tool
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
