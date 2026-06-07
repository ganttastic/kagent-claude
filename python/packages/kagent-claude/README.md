# kagent-claude

Claude Agent SDK integration for [kagent](https://kagent.dev) with A2A server support.

## Overview

`kagent-claude` enables the Claude Agent SDK to run as a BYO (Bring Your Own) agent inside the kagent platform. It follows the same architectural pattern as `kagent-crewai` and `kagent-langgraph`.

## Installation

```bash
pip install kagent-claude
```

## Quick Start

```python
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import KAgentApp
from kagent.core import KAgentConfig
from a2a.types import AgentCard, AgentCapabilities, AgentSkill

app = KAgentApp(
    options=ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "WebSearch"],
    ),
    agent_card=AgentCard(
        name="my-claude-agent",
        description="A Claude-powered kagent agent",
        url="http://my-claude-agent:8080/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[
            AgentSkill(
                id="code",
                name="Code generation",
                description="Generates and modifies code",
                tags=["coding"],
            )
        ],
    ),
    config=KAgentConfig(
        url="http://kagent-controller:8083",
        name="my-claude-agent",
        namespace="kagent",
    ),
)

if __name__ == "__main__":
    app.run(port=8080)
```

## Session Continuity

The package maps A2A `contextId` to Claude Agent SDK `session_id`, enabling multi-turn conversations that preserve Claude's context window across requests within the same context.

## Environment Variables

- `ANTHROPIC_API_KEY` — Required for Claude Agent SDK authentication
- `KAGENT_URL` — kagent controller URL (alternative to passing in config)
- `KAGENT_NAME` — Agent name (alternative to passing in config)
- `KAGENT_NAMESPACE` — Agent namespace (alternative to passing in config)
