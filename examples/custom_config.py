"""
Example: Custom configuration with timeout, streaming, and system prompt.

Demonstrates all ClaudeExecutorConfig options and ClaudeAgentOptions
customization.

Run locally:
    ANTHROPIC_API_KEY=sk-... KAGENT_URL=http://localhost:8083 \
    KAGENT_NAME=custom-agent KAGENT_NAMESPACE=default \
    python examples/custom_config.py
"""

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import ClaudeExecutorConfig, KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    # Claude Agent SDK options — controls what Claude can do
    options=ClaudeAgentOptions(
        # Tools the agent can use (from the Claude Agent SDK tool set)
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch"],
        # System prompt — instructs Claude's behavior
        system_prompt=(
            "You are a senior infrastructure engineer. "
            "Always explain your reasoning before taking action. "
            "Prefer read-only operations unless the user explicitly asks for changes."
        ),
        # Max turns before Claude stops (prevents runaway loops)
        max_turns=20,
    ),
    # Executor config — controls runtime behavior
    executor_config=ClaudeExecutorConfig(
        # Kill the query if it takes longer than 10 minutes
        execution_timeout=600.0,
        # Stream tool calls/results to the dashboard in real-time
        enable_streaming=True,
        # Don't require approval — tools in allowed_tools run automatically
        enable_hitl=False,
    ),
    # Agent identity for A2A protocol
    agent_card=AgentCard(
        name="custom-agent",
        description="Infrastructure research agent with custom timeouts",
        url="http://localhost:8080/",
        version="0.2.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="infra",
                name="Infrastructure research",
                description="Analyze infrastructure, read configs, research solutions",
                tags=["infra", "research"],
                examples=[
                    "What Kubernetes resources are running in the cluster?",
                    "Analyze the nginx config for security issues",
                ],
            )
        ],
    ),
    # KAgent platform config — usually auto-injected by the controller
    config=KAgentConfig(),
    # OpenTelemetry tracing (disable for local dev if no collector running)
    tracing=False,
)

if __name__ == "__main__":
    app.run(port=8080)
