"""
Example: Human-in-the-Loop (HITL) agent.

This agent requires user approval before executing any tool.
The kagent dashboard shows a confirmation dialog with tool name and arguments.

Run locally:
    ANTHROPIC_API_KEY=sk-... KAGENT_URL=http://localhost:8083 \
    KAGENT_NAME=hitl-agent KAGENT_NAMESPACE=default \
    python examples/hitl.py

Test the HITL flow with curl:

1. Send a message that triggers a tool:
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
            "parts": [{"kind": "text", "text": "List the files in /tmp"}]
          }
        }
      }'

2. The response will have state: "input_required" with a DataPart showing
   the tool call (Bash: ls /tmp) waiting for approval.

3. Approve the tool call:
    curl -X POST http://localhost:8080/ \
      -H "Content-Type: application/json" \
      -d '{
        "jsonrpc": "2.0",
        "id": "2",
        "method": "message/send",
        "params": {
          "message": {
            "messageId": "msg-002",
            "role": "user",
            "parts": [{
              "kind": "data",
              "data": {"decision_type": "approve"}
            }]
          }
        }
      }'

4. Or deny it:
    curl -X POST http://localhost:8080/ \
      -H "Content-Type: application/json" \
      -d '{
        "jsonrpc": "2.0",
        "id": "2",
        "method": "message/send",
        "params": {
          "message": {
            "messageId": "msg-002",
            "role": "user",
            "parts": [{
              "kind": "data",
              "data": {
                "decision_type": "reject",
                "rejection_reason": "I don't want to list /tmp"
              }
            }]
          }
        }
      }'
"""

from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import ClaudeAgentExecutorConfig, KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write", "Glob", "Grep"],
    ),
    agent_card=AgentCard(
        name="hitl-agent",
        description="Claude agent with human-in-the-loop approval for all tool use",
        url="http://localhost:8080/",
        version="0.2.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="code",
                name="Code assistance (with approval)",
                description="Read and modify code, with user approval for each action",
                tags=["coding", "hitl"],
            )
        ],
    ),
    executor_config=ClaudeAgentExecutorConfig(
        enable_hitl=True,
        execution_timeout=600.0,  # 10 min — HITL can take time
    ),
    config=KAgentConfig(),
)

if __name__ == "__main__":
    app.run(port=8080)
