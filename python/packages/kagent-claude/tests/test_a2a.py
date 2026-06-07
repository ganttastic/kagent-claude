"""Smoke test for KAgentApp server wiring."""

from unittest.mock import MagicMock, patch

import pytest
from a2a.types import AgentCapabilities, AgentCard, AgentSkill


@pytest.fixture
def mock_kagent_config():
    config = MagicMock()
    config.url = "http://localhost:8083"
    config.name = "test-agent"
    config.namespace = "default"
    config.app_name = "test-agent"
    return config


@pytest.fixture
def agent_card():
    return AgentCard(
        name="test-agent",
        description="Test agent",
        url="http://localhost:8080/",
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="test",
                name="Test skill",
                description="A test skill",
                tags=["test"],
            )
        ],
    )


def test_build_returns_fastapi_app(mock_kagent_config, agent_card):
    """KAgentApp.build() returns a FastAPI app with expected routes."""
    with patch("kagent.claude._a2a.configure_logging"), patch(
        "kagent.claude._a2a.configure_tracing"
    ):
        from kagent.claude._a2a import KAgentApp

        options = MagicMock()
        options.__dict__ = {"allowed_tools": ["Bash"]}

        app_builder = KAgentApp(
            options=options,
            agent_card=agent_card,
            config=mock_kagent_config,
            tracing=False,  # skip OTel in tests
        )

        fastapi_app = app_builder.build()

    # Verify it's a FastAPI app
    from fastapi import FastAPI

    assert isinstance(fastapi_app, FastAPI)

    # Verify health and thread_dump routes are registered
    route_paths = [route.path for route in fastapi_app.routes]
    assert "/health" in route_paths
    assert "/thread_dump" in route_paths

    # Verify the app has a title containing the agent name
    assert "test-agent" in fastapi_app.title
