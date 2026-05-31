"""ClaudeAgentExecutor — bridges the Claude Agent SDK to the A2A AgentExecutor interface."""

import logging
import uuid
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
from kagent.core.tracing._span_processor import (
    clear_kagent_span_attributes,
    set_kagent_span_attributes,
)

from ._session_store import ClaudeSessionStore

logger = logging.getLogger(__name__)


class ClaudeAgentExecutor(AgentExecutor):
    """
    Bridges the Claude Agent SDK to the A2A AgentExecutor interface.

    Streams Claude's async message iterator into A2A TaskStatusUpdateEvents,
    resuming the correct Claude session via contextId <-> session_id mapping.
    """

    def __init__(
        self,
        *,
        options: ClaudeAgentOptions,
        session_store: ClaudeSessionStore,
        app_name: str = "kagent-claude",
    ):
        super().__init__()
        self.options = options
        self.session_store = session_store
        self.app_name = app_name

    @override
    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        raise NotImplementedError("Cancellation is not supported by the Claude Agent SDK executor.")

    @override
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ):
        if not context.message:
            raise ValueError("A2A request must have a message")

        span_attributes = _build_span_attributes(context)
        context_token = set_kagent_span_attributes(span_attributes)
        try:
            # Extract user input
            user_input = context.get_user_input()
            if not user_input:
                user_input = _extract_text(context.message)
            context_id = context.context_id

            # Look up existing Claude session for this context
            claude_session_id = self.session_store.get(context_id) if context_id else None

            # Build options, injecting resume if we have a prior session
            options = self.options
            if claude_session_id:
                # resume is a field on ClaudeAgentOptions, not a query() param
                options = ClaudeAgentOptions(
                    **{
                        k: v
                        for k, v in self.options.__dict__.items()
                        if v is not None
                    },
                    resume=claude_session_id,
                )

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

            # Signal working state
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=context.task_id,
                    status=TaskStatus(
                        state=TaskState.working,
                        timestamp=datetime.now(timezone.utc).isoformat(),
                    ),
                    context_id=context.context_id,
                    final=False,
                    metadata={
                        "app_name": self.app_name,
                        "session_id": context.context_id,
                    },
                )
            )

            # Stream Claude Agent SDK responses
            accumulated_text: list[str] = []
            new_session_id: str | None = None
            try:
                async for message in query(
                    prompt=user_input,
                    options=options,
                ):
                    # Capture session_id from SystemMessage init event
                    if (
                        new_session_id is None
                        and isinstance(message, SystemMessage)
                        and getattr(message, "subtype", None) == "init"
                        and hasattr(message, "data")
                        and isinstance(message.data, dict)
                    ):
                        new_session_id = message.data.get("session_id")

                    # Collect final result text (ResultMessage)
                    if hasattr(message, "result") and message.result:
                        accumulated_text.append(message.result)

            except Exception as e:
                logger.error(f"Error during Claude Agent SDK execution: {e}", exc_info=True)
                await event_queue.enqueue_event(
                    TaskStatusUpdateEvent(
                        task_id=context.task_id,
                        status=TaskStatus(
                            state=TaskState.failed,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            message=Message(
                                message_id=str(uuid.uuid4()),
                                role=Role.agent,
                                parts=[Part(TextPart(text=str(e)))],
                            ),
                        ),
                        context_id=context.context_id,
                        final=True,
                    )
                )
                return

            # Persist session mapping for next turn
            if new_session_id and context_id:
                self.session_store.set(context_id, new_session_id)

            # Emit final artifact and completed status
            final_text = "".join(accumulated_text) or "No response was generated."
            await event_queue.enqueue_event(
                TaskArtifactUpdateEvent(
                    task_id=context.task_id,
                    last_chunk=True,
                    context_id=context.context_id,
                    artifact=Artifact(
                        artifact_id=str(uuid.uuid4()),
                        parts=[Part(TextPart(text=final_text))],
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
                )
            )
        finally:
            clear_kagent_span_attributes(context_token)


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
