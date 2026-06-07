"""
Minimal programmatic agent — equivalent to the golden image with defaults.

For most use cases, you don't need this file. The golden image
(ghcr.io/ganttastic/kagent-claude) is fully configurable via env vars.

Use this pattern when you need something the env vars can't express:
- MCP server configuration
- Custom hooks or callbacks
- Custom session store implementations
- Complex skill definitions

Run locally:
    ANTHROPIC_API_KEY=sk-... KAGENT_URL=http://localhost:8083 \
    KAGENT_NAME=claude-agent KAGENT_NAMESPACE=default \
    python examples/basic.py
"""

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Glob", "Grep"],
    ),
    agent_card=AgentCard(
        name="claude-example-agent",
        description="Example Claude-powered coding agent running on kagent",
        url="http://localhost:8080/",
        version="0.2.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="code",
                name="Code assistance",
                description="Read, analyze, and modify code using Claude",
                tags=["coding", "analysis"],
                examples=[
                    "What files are in this directory?",
                    "Find all TODO comments in the codebase",
                    "Explain how the authentication module works",
                ],
            )
        ],
    ),
    config=KAgentConfig(),
)

if __name__ == "__main__":
    app.run(port=8080)
