"""
Example: MCP server integration with custom system prompt.

This example shows the primary reason to write Python instead of using
the golden image: MCP server configuration. MCP servers let Claude
interact with external tools (databases, APIs, custom CLIs) that aren't
part of the built-in tool set.

Run locally:
    ANTHROPIC_API_KEY=sk-... KAGENT_URL=http://localhost:8083 \
    KAGENT_NAME=custom-agent KAGENT_NAMESPACE=default \
    python examples/custom_config.py
"""

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import ClaudeAgentExecutorConfig, KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        # Built-in tools
        allowed_tools=["Bash", "Read", "Glob", "Grep", "WebFetch"],
        # System prompt — controls Claude's behavior
        system_prompt=(
            "You are a senior infrastructure engineer. "
            "Always explain your reasoning before taking action. "
            "Prefer read-only operations unless the user explicitly asks for changes."
        ),
        max_turns=20,
        # MCP servers — this is why you'd write code instead of using env vars.
        # Each server is a subprocess that Claude can call as a tool.
        # mcp_servers={
        #     "postgres": {
        #         "command": "npx",
        #         "args": ["@modelcontextprotocol/server-postgres", "postgresql://..."],
        #     },
        #     "github": {
        #         "command": "npx",
        #         "args": ["@modelcontextprotocol/server-github"],
        #         "env": {"GITHUB_TOKEN": os.environ["GITHUB_TOKEN"]},
        #     },
        # },
    ),
    executor_config=ClaudeAgentExecutorConfig(
        execution_timeout=600.0,
        enable_streaming=True,
        enable_hitl=False,
    ),
    agent_card=AgentCard(
        name="custom-agent",
        description="Infrastructure research agent with MCP integration",
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
    config=KAgentConfig(),
    tracing=False,
)

if __name__ == "__main__":
    app.run(port=8080)
