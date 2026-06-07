"""
HITL (Human-in-the-Loop) bridge for the Claude Agent SDK.

Bridges the Claude Agent SDK's synchronous `can_use_tool` callback to kagent's
async A2A input_required/resume cycle.

Flow:
1. Claude wants to use a tool → `can_use_tool` callback fires
2. Bridge creates an asyncio.Future and emits TaskStatusUpdateEvent(input_required)
3. The executor's execute() returns, leaving the query paused
4. User responds via kagent dashboard → next execute() call on same task
5. Bridge resolves the Future with the user's decision
6. `can_use_tool` returns PermissionResultAllow or PermissionResultDeny
7. Claude continues execution
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny
from kagent.core.a2a import (
    A2A_DATA_PART_METADATA_IS_LONG_RUNNING_KEY,
    A2A_DATA_PART_METADATA_TYPE_FUNCTION_CALL,
    A2A_DATA_PART_METADATA_TYPE_KEY,
    KAGENT_ASK_USER_ANSWERS_KEY,
    KAGENT_HITL_DECISION_TYPE_APPROVE,
    KAGENT_HITL_DECISION_TYPE_BATCH,
    KAGENT_HITL_DECISION_TYPE_KEY,
    KAGENT_HITL_DECISION_TYPE_REJECT,
    KAGENT_HITL_DECISIONS_KEY,
    KAGENT_HITL_REJECTION_REASONS_KEY,
    extract_ask_user_answers_from_message,
    extract_batch_decisions_from_message,
    extract_decision_from_message,
    extract_rejection_reasons_from_message,
)

logger = logging.getLogger(__name__)


@dataclass
class PendingApproval:
    """A tool approval request waiting for user decision."""

    confirmation_id: str
    tool_name: str
    tool_input: dict
    tool_use_id: str | None = None
    future: asyncio.Future = field(default=None, init=False)

    def __post_init__(self):
        # Create the future lazily — requires a running event loop
        loop = asyncio.get_running_loop()
        self.future = loop.create_future()


@dataclass
class ApprovalDecision:
    """User's decision on a pending approval."""

    approved: bool
    updated_input: dict | None = None
    rejection_reason: str | None = None


class HitlBridge:
    """
    Manages pending tool approval requests between the Claude Agent SDK
    and kagent's A2A HITL protocol.

    Each context_id can have multiple pending approvals (batch).
    """

    def __init__(self):
        # context_id -> list of pending approvals
        self._pending: dict[str, list[PendingApproval]] = {}
        # context_id -> event signalled when a new approval is created
        self._notify_events: dict[str, asyncio.Event] = {}

    def register_notify_event(self, context_id: str, event: asyncio.Event) -> None:
        """Register an event to be set when a new approval is created for this context."""
        self._notify_events[context_id] = event

    def unregister_notify_event(self, context_id: str) -> None:
        """Remove the notification event for a context."""
        self._notify_events.pop(context_id, None)

    def has_pending(self, context_id: str) -> bool:
        """Check if there are unresolved approvals for this context."""
        return bool(self._pending.get(context_id))

    def get_pending(self, context_id: str) -> list[PendingApproval]:
        """Get all pending approvals for a context."""
        return self._pending.get(context_id, [])

    def create_approval(
        self,
        context_id: str,
        tool_name: str,
        tool_input: dict,
        tool_use_id: str | None = None,
    ) -> PendingApproval:
        """
        Create a new pending approval for a tool use request.
        Returns the PendingApproval whose future will be resolved when
        the user responds.
        """
        approval = PendingApproval(
            confirmation_id=str(uuid.uuid4()),
            tool_name=tool_name,
            tool_input=tool_input,
            tool_use_id=tool_use_id,
        )

        if context_id not in self._pending:
            self._pending[context_id] = []
        self._pending[context_id].append(approval)

        logger.debug(
            f"Created pending approval {approval.confirmation_id} "
            f"for tool {tool_name} in context {context_id}"
        )

        # Signal the executor that HITL input is needed
        notify = self._notify_events.get(context_id)
        if notify:
            notify.set()

        return approval

    def resolve_all(self, context_id: str, decision: ApprovalDecision) -> None:
        """Resolve all pending approvals for a context with the same decision."""
        pending = self._pending.pop(context_id, [])
        for approval in pending:
            if not approval.future.done():
                approval.future.set_result(decision)

    def resolve_batch(
        self,
        context_id: str,
        decisions: dict[str, str],
        rejection_reasons: dict[str, str] | None = None,
    ) -> None:
        """
        Resolve pending approvals individually (batch mode).
        decisions maps confirmation_id or tool_use_id -> "approve"/"reject"
        """
        pending = self._pending.pop(context_id, [])
        rejection_reasons = rejection_reasons or {}

        for approval in pending:
            if approval.future.done():
                continue

            # Match by confirmation_id or tool_use_id
            decision_str = (
                decisions.get(approval.confirmation_id)
                or decisions.get(approval.tool_use_id or "")
            )

            if decision_str == KAGENT_HITL_DECISION_TYPE_APPROVE:
                approval.future.set_result(
                    ApprovalDecision(approved=True, updated_input=approval.tool_input)
                )
            else:
                reason = (
                    rejection_reasons.get(approval.confirmation_id)
                    or rejection_reasons.get(approval.tool_use_id or "")
                    or "User rejected this action"
                )
                approval.future.set_result(
                    ApprovalDecision(approved=False, rejection_reason=reason)
                )

    def cancel_all(self, context_id: str) -> None:
        """Cancel all pending approvals (e.g., on task failure or timeout)."""
        pending = self._pending.pop(context_id, [])
        for approval in pending:
            if not approval.future.done():
                approval.future.cancel()
        self.unregister_notify_event(context_id)


def build_confirmation_data_part(approval: PendingApproval) -> dict:
    """
    Build the A2A DataPart data dict for an approval request,
    matching kagent's adk_request_confirmation format.
    """
    return {
        "name": "adk_request_confirmation",
        "id": approval.confirmation_id,
        "args": {
            "originalFunctionCall": {
                "name": approval.tool_name,
                "args": approval.tool_input,
                "id": approval.tool_use_id or approval.confirmation_id,
            },
            "toolConfirmation": {
                "hint": f"Tool '{approval.tool_name}' requires approval before execution.",
                "confirmed": False,
                "payload": None,
            },
        },
    }


def build_confirmation_metadata() -> dict:
    """Build the A2A DataPart metadata for an approval request."""
    return {
        A2A_DATA_PART_METADATA_TYPE_KEY: A2A_DATA_PART_METADATA_TYPE_FUNCTION_CALL,
        A2A_DATA_PART_METADATA_IS_LONG_RUNNING_KEY: True,
    }


def extract_hitl_decision_from_message(message) -> tuple[str, dict[str, str], dict[str, str]] | None:
    """
    Extract HITL decision from an A2A message using kagent-core utilities.
    Returns (decision_type, decisions_dict, rejection_reasons) or None.

    Supports both real A2A Message objects and raw message-like objects
    with .parts containing DataParts or dicts.
    """
    if not message:
        return None

    # Try kagent-core's extract first (works with real A2A Message objects)
    decision_type = extract_decision_from_message(message)

    # Fallback: check raw .data on parts (for cases where parts aren't wrapped in RootModel)
    if not decision_type and hasattr(message, "parts") and message.parts:
        for part in message.parts:
            data = None
            if hasattr(part, "data") and isinstance(getattr(part, "data", None), dict):
                data = part.data
            elif hasattr(part, "root") and hasattr(part.root, "data") and isinstance(part.root.data, dict):
                data = part.root.data

            if data and KAGENT_HITL_DECISION_TYPE_KEY in data:
                decision_type = data[KAGENT_HITL_DECISION_TYPE_KEY]
                break

    if not decision_type:
        return None

    # Extract batch decisions and rejection reasons
    decisions = extract_batch_decisions_from_message(message) or {}
    rejection_reasons = extract_rejection_reasons_from_message(message) or {}

    # Fallback: extract from raw parts if core utilities didn't find them
    if not decisions or not rejection_reasons:
        if hasattr(message, "parts") and message.parts:
            for part in message.parts:
                data = None
                if hasattr(part, "data") and isinstance(getattr(part, "data", None), dict):
                    data = part.data
                elif hasattr(part, "root") and hasattr(part.root, "data") and isinstance(part.root.data, dict):
                    data = part.root.data

                if not isinstance(data, dict):
                    continue

                if not decisions and KAGENT_HITL_DECISIONS_KEY in data:
                    decisions = data[KAGENT_HITL_DECISIONS_KEY]
                if not rejection_reasons and KAGENT_HITL_REJECTION_REASONS_KEY in data:
                    rejection_reasons = data[KAGENT_HITL_REJECTION_REASONS_KEY]

                # Single rejection_reason field
                if not rejection_reasons:
                    reason = data.get("rejection_reason")
                    if reason:
                        rejection_reasons = {"__all__": reason}

    return (decision_type, decisions, rejection_reasons)


async def make_can_use_tool_callback(bridge: HitlBridge, context_id: str):
    """
    Factory that creates a `can_use_tool` callback wired to the HITL bridge.

    The returned callback pauses Claude's execution by awaiting a Future,
    which is resolved when the user responds via the A2A protocol.
    """

    async def can_use_tool(
        tool_name: str, input_data: dict, context
    ) -> PermissionResultAllow | PermissionResultDeny:
        # Create a pending approval and wait for the user's decision
        approval = bridge.create_approval(
            context_id=context_id,
            tool_name=tool_name,
            tool_input=input_data,
            tool_use_id=getattr(context, "tool_use_id", None),
        )

        # This await pauses Claude's execution until resolve is called
        decision: ApprovalDecision = await approval.future

        if decision.approved:
            return PermissionResultAllow(
                updated_input=decision.updated_input or input_data
            )
        else:
            return PermissionResultDeny(
                message=decision.rejection_reason or "User denied this action"
            )

    return can_use_tool


def extract_ask_user_answers_text(message) -> str | None:
    """
    Extract ask-user answer text from an A2A message.

    When a user responds to a question from Claude (via the kagent dashboard),
    the response comes as a DataPart with ask_user_answers. This function
    extracts the answer text that should be passed back to Claude as the
    next prompt on the resumed session.

    Returns the concatenated answer text, or None if the message doesn't
    contain ask-user answers.
    """
    if not message:
        return None

    # Try kagent-core's extraction first (works with real A2A DataParts)
    answers = extract_ask_user_answers_from_message(message)

    # Fallback: raw part inspection for non-standard messages
    if not answers and hasattr(message, "parts") and message.parts:
        for part in message.parts:
            data = None
            if hasattr(part, "data") and isinstance(getattr(part, "data", None), dict):
                data = part.data
            elif hasattr(part, "root") and hasattr(part.root, "data") and isinstance(getattr(part.root, "data", None), dict):
                data = part.root.data

            if isinstance(data, dict) and KAGENT_ASK_USER_ANSWERS_KEY in data:
                answers = data[KAGENT_ASK_USER_ANSWERS_KEY]
                break

    if not answers:
        return None

    # Extract text from the answers list
    # Each answer is typically {"answer": ["text1", "text2", ...]}
    texts: list[str] = []
    for answer_dict in answers:
        if isinstance(answer_dict, dict):
            answer_values = answer_dict.get("answer", [])
            if isinstance(answer_values, list):
                texts.extend(str(v) for v in answer_values if v)
            elif isinstance(answer_values, str):
                texts.append(answer_values)
        elif isinstance(answer_dict, str):
            texts.append(answer_dict)

    return "\n".join(texts) if texts else None
