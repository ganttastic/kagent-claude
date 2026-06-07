"""Shared test fixtures for kagent-claude tests."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from a2a.types import Message, Role, TextPart

from kagent.claude._executor import ClaudeAgentExecutor, ClaudeAgentExecutorConfig
from kagent.claude._session_store import ClaudeSessionStore


class MockSystemMessage:
    """Mock Claude SDK SystemMessage with init subtype."""

    def __init__(self, session_id: str):
        self.subtype = "init"
        self.data = {"session_id": session_id}


class MockResultMessage:
    """Mock Claude SDK ResultMessage with result text."""

    def __init__(self, result: str = ""):
        self.result = result


class MockAssistantMessage:
    """Mock Claude SDK AssistantMessage with content blocks."""

    def __init__(self, content=None):
        self.content = content or []


class MockToolUseBlock:
    """Mock Claude SDK ToolUseBlock."""

    def __init__(self, name: str = "Bash", input: dict = None, id: str = "tool-1"):
        self.type = "tool_use"
        self.name = name
        self.input = input or {"command": "ls"}
        self.id = id


class MockTextBlock:
    """Mock Claude SDK TextBlock."""

    def __init__(self, text: str = "thinking..."):
        self.type = "text"
        self.text = text


async def async_iter(items):
    """Helper to create an async generator from a list."""
    for item in items:
        yield item


@pytest.fixture
def session_store():
    return ClaudeSessionStore()


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
    ctx.message = Message(
        message_id="msg-test-001",
        role=Role.user,
        parts=[TextPart(text="Hello Claude")],
    )
    ctx.get_user_input = MagicMock(return_value="Hello Claude")
    ctx.call_context = None
    return ctx


def make_executor(session_store, **config_kwargs) -> ClaudeAgentExecutor:
    """Factory for creating executors with custom config."""
    options = MagicMock()
    options.__dict__ = {"allowed_tools": ["Bash"]}
    config = ClaudeAgentExecutorConfig(**config_kwargs)
    return ClaudeAgentExecutor(
        options=options,
        session_store=session_store,
        app_name="test-agent",
        config=config,
    )


@pytest.fixture
def executor(session_store):
    return make_executor(session_store, enable_streaming=False)


@pytest.fixture
def streaming_executor(session_store):
    return make_executor(session_store, enable_streaming=True)


@pytest.fixture
def hitl_executor(session_store):
    return make_executor(session_store, enable_hitl=True, enable_streaming=False)


@pytest.fixture
def patch_executor_deps():
    """Context manager that patches all executor external dependencies."""
    with (
        patch("kagent.claude._executor.query") as mock_query,
        patch("kagent.claude._executor.SystemMessage", MockSystemMessage),
        patch("kagent.claude._executor.set_kagent_span_attributes", return_value=None),
        patch("kagent.claude._executor.clear_kagent_span_attributes"),
    ):
        yield mock_query
