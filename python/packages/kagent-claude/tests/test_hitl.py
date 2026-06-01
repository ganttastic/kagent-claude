"""Tests for HITL bridge and executor HITL integration."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kagent.claude._hitl import (
    DECISION_APPROVE,
    DECISION_BATCH,
    DECISION_REJECT,
    ApprovalDecision,
    HitlBridge,
    build_confirmation_data_part,
    build_confirmation_metadata,
    extract_decision_from_message,
    make_can_use_tool_callback,
)


class TestHitlBridge:
    def test_has_pending_false_initially(self):
        bridge = HitlBridge()
        assert bridge.has_pending("ctx-1") is False

    def test_create_approval_makes_pending(self):
        bridge = HitlBridge()
        approval = bridge.create_approval("ctx-1", "Bash", {"command": "rm -rf /"})
        assert bridge.has_pending("ctx-1") is True
        assert approval.tool_name == "Bash"
        assert approval.tool_input == {"command": "rm -rf /"}

    def test_resolve_all_approve(self):
        bridge = HitlBridge()
        approval = bridge.create_approval("ctx-1", "Bash", {"command": "ls"})

        decision = ApprovalDecision(approved=True, updated_input={"command": "ls"})
        bridge.resolve_all("ctx-1", decision)

        assert approval.future.done()
        assert approval.future.result().approved is True
        assert bridge.has_pending("ctx-1") is False

    def test_resolve_all_reject(self):
        bridge = HitlBridge()
        approval = bridge.create_approval("ctx-1", "Write", {"file_path": "/etc/passwd"})

        decision = ApprovalDecision(approved=False, rejection_reason="Dangerous path")
        bridge.resolve_all("ctx-1", decision)

        assert approval.future.result().approved is False
        assert approval.future.result().rejection_reason == "Dangerous path"

    def test_resolve_batch(self):
        bridge = HitlBridge()
        a1 = bridge.create_approval("ctx-1", "Bash", {"command": "ls"}, tool_use_id="tool-1")
        a2 = bridge.create_approval("ctx-1", "Write", {"file_path": "x"}, tool_use_id="tool-2")

        bridge.resolve_batch(
            "ctx-1",
            decisions={"tool-1": "approve", "tool-2": "reject"},
            rejection_reasons={"tool-2": "Not allowed"},
        )

        assert a1.future.result().approved is True
        assert a2.future.result().approved is False
        assert a2.future.result().rejection_reason == "Not allowed"

    def test_cancel_all(self):
        bridge = HitlBridge()
        approval = bridge.create_approval("ctx-1", "Bash", {"command": "ls"})
        bridge.cancel_all("ctx-1")
        assert approval.future.cancelled()
        assert bridge.has_pending("ctx-1") is False

    def test_multiple_contexts_independent(self):
        bridge = HitlBridge()
        bridge.create_approval("ctx-1", "Bash", {"command": "ls"})
        bridge.create_approval("ctx-2", "Write", {"file_path": "x"})

        bridge.resolve_all("ctx-1", ApprovalDecision(approved=True))
        assert bridge.has_pending("ctx-1") is False
        assert bridge.has_pending("ctx-2") is True


class TestBuildConfirmationParts:
    def test_data_part_structure(self):
        from kagent.claude._hitl import PendingApproval

        approval = PendingApproval(
            confirmation_id="conf-123",
            tool_name="Bash",
            tool_input={"command": "rm -rf /tmp/data"},
            tool_use_id="tool-456",
        )
        data = build_confirmation_data_part(approval)

        assert data["name"] == "adk_request_confirmation"
        assert data["id"] == "conf-123"
        assert data["args"]["originalFunctionCall"]["name"] == "Bash"
        assert data["args"]["originalFunctionCall"]["args"] == {"command": "rm -rf /tmp/data"}
        assert data["args"]["originalFunctionCall"]["id"] == "tool-456"
        assert data["args"]["toolConfirmation"]["confirmed"] is False

    def test_metadata_structure(self):
        meta = build_confirmation_metadata()
        assert meta["kagent_type"] == "function_call"
        assert meta["kagent_is_long_running"] is True


class TestExtractDecision:
    def test_approve_decision(self):
        part = MagicMock()
        part.data = {"decision_type": "approve"}
        part.root = None

        message = MagicMock()
        message.parts = [part]

        result = extract_decision_from_message(message)
        assert result is not None
        decision_type, decisions, reasons = result
        assert decision_type == "approve"

    def test_reject_with_reason(self):
        part = MagicMock()
        part.data = {"decision_type": "reject", "rejection_reason": "Too dangerous"}

        message = MagicMock()
        message.parts = [part]

        result = extract_decision_from_message(message)
        decision_type, decisions, reasons = result
        assert decision_type == "reject"
        assert reasons["__all__"] == "Too dangerous"

    def test_batch_decision(self):
        part = MagicMock()
        part.data = {
            "decision_type": "batch",
            "decisions": {"tool-1": "approve", "tool-2": "reject"},
            "rejection_reasons": {"tool-2": "Nope"},
        }

        message = MagicMock()
        message.parts = [part]

        result = extract_decision_from_message(message)
        decision_type, decisions, reasons = result
        assert decision_type == "batch"
        assert decisions["tool-1"] == "approve"
        assert reasons["tool-2"] == "Nope"

    def test_no_decision_in_message(self):
        part = MagicMock()
        part.data = {"some_other_key": "value"}

        message = MagicMock()
        message.parts = [part]

        assert extract_decision_from_message(message) is None

    def test_none_message(self):
        assert extract_decision_from_message(None) is None


@pytest.mark.asyncio
async def test_can_use_tool_callback_approve():
    """The callback pauses until resolved, then returns Allow."""
    bridge = HitlBridge()
    callback = await make_can_use_tool_callback(bridge, "ctx-1")

    # Start the callback in a task (it will block on the future)
    task = asyncio.create_task(
        callback("Bash", {"command": "ls"}, MagicMock())
    )

    # Give it a moment to create the pending approval
    await asyncio.sleep(0.01)
    assert bridge.has_pending("ctx-1")

    # Resolve it
    bridge.resolve_all("ctx-1", ApprovalDecision(approved=True, updated_input={"command": "ls"}))

    result = await task
    # Should be PermissionResultAllow
    assert hasattr(result, "updated_input")


@pytest.mark.asyncio
async def test_can_use_tool_callback_deny():
    """The callback returns Deny when rejected."""
    bridge = HitlBridge()
    callback = await make_can_use_tool_callback(bridge, "ctx-1")

    task = asyncio.create_task(
        callback("Write", {"file_path": "/etc/shadow"}, MagicMock())
    )
    await asyncio.sleep(0.01)

    bridge.resolve_all(
        "ctx-1",
        ApprovalDecision(approved=False, rejection_reason="Access denied"),
    )

    result = await task
    assert hasattr(result, "message")
    assert "Access denied" in result.message
