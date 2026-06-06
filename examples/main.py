"""
Example kagent-claude BYO agent.

Run locally (without kagent controller):
    ANTHROPIC_API_KEY=sk-... KAGENT_URL=http://localhost:8083 KAGENT_NAME=claude-agent KAGENT_NAMESPACE=default python examples/main.py

Then send an A2A message:
    curl -X POST http://localhost:8080/ \
      -H "Content-Type: application/json" \
      -d '{
        "jsonrpc": "2.0",
        "id": "1",
        "method": "message/send",
        "params": {
          "message": {
            "messageId": "msg-001",
            "role": "user",
            "parts": [{"kind": "text", "text": "What files are in the current directory?"}]
          }
        }
      }'
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
        url="http://claude-example-agent.kagent.svc.cluster.local:8080/",
        version="0.1.0",
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
    config=KAgentConfig(),  # reads from KAGENT_URL, KAGENT_NAME, KAGENT_NAMESPACE env vars
)

if __name__ == "__main__":
    app.run(port=8080)
