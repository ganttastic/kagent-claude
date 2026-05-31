"""kagent-claude BYO agent for homelab deployment."""

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"],
    ),
    agent_card=AgentCard(
        name="claude-agent",
        description="Claude-powered coding and research agent",
        url="http://claude-agent.kagent.svc.cluster.local:8080/",
        version="0.1.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="code",
                name="Code assistance",
                description="Read, analyze, and modify code",
                tags=["coding", "analysis"],
                examples=[
                    "Find all TODO comments in the codebase",
                    "Explain how the authentication module works",
                ],
            ),
            AgentSkill(
                id="research",
                name="Web research",
                description="Search and fetch web content for research",
                tags=["research", "web"],
                examples=[
                    "What are the latest changes in Python 3.13?",
                    "Find documentation for the FastAPI middleware pattern",
                ],
            ),
        ],
    ),
    config=KAgentConfig(),
)

if __name__ == "__main__":
    app.run(port=8080)
