# kagent-claude

A Python integration package that runs the [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/overview) as a BYO (Bring Your Own) agent inside the [kagent](https://kagent.dev) platform.

Once deployed, your Claude agent is a first-class kagent citizen — visible in the dashboard, invocable via CLI, chainable with other agents, and observable via OpenTelemetry.

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  kagent platform (Kubernetes)                       │
│                                                     │
│  ┌───────────────┐    A2A protocol    ┌──────────┐  │
│  │ kagent        │◄──────────────────►│ kagent-  │  │
│  │ controller    │                    │ claude   │  │
│  └───────────────┘                    └────┬─────┘  │
│                                            │        │
│                                            ▼        │
│                                     Claude Agent    │
│                                     SDK (query())   │
└─────────────────────────────────────────────────────┘
```

The package wraps `ClaudeAgentOptions` in a `KAgentApp` class that builds an [A2A-compliant](https://a2a-protocol.org) FastAPI server. The `ClaudeAgentExecutor` translates between A2A message events and the Claude Agent SDK's async streaming interface.

## Installation

```bash
pip install kagent-claude
```

Requires Python 3.10+.

## Quick Start

```python
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
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
                name="Code assistance",
                description="Read, analyze, and modify code",
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

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key from [console.anthropic.com](https://console.anthropic.com) |
| `KAGENT_URL` | Yes | kagent controller URL (or pass via `KAgentConfig(url=...)`) |
| `KAGENT_NAME` | Yes | Agent name matching the Agent CRD (or pass via config) |
| `KAGENT_NAMESPACE` | Yes | Kubernetes namespace (or pass via config) |

### ClaudeAgentOptions

All [Claude Agent SDK options](https://code.claude.com/docs/en/agent-sdk/overview) are supported:

```python
ClaudeAgentOptions(
    allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"],
    system_prompt="You are a helpful coding assistant.",
    max_turns=10,
    mcp_servers={
        "my-server": {
            "command": "npx",
            "args": ["@my-org/my-mcp-server"],
        }
    },
)
```

## Architecture

### Package Structure

```
python/packages/kagent-claude/src/kagent/claude/
├── __init__.py          # Public exports: KAgentApp, ClaudeAgentExecutor, ClaudeSessionStore
├── _a2a.py              # KAgentApp — assembles FastAPI server with A2A routes
├── _executor.py         # ClaudeAgentExecutor — A2A AgentExecutor implementation
└── _session_store.py    # Maps A2A contextId to Claude session_id
```

### Key Components

**`KAgentApp`** — The public entrypoint. Wires together the executor, task store, request handler, and A2A application into a runnable FastAPI server. Follows the same pattern as `kagent-crewai` and `kagent-langgraph`.

**`ClaudeAgentExecutor`** — Implements the A2A `AgentExecutor` interface. On each `execute()` call:
1. Extracts user text from the A2A message
2. Looks up any existing Claude session for the context
3. Calls `query(prompt, options)` with `resume` set in options if resuming
4. Streams responses, capturing the `session_id` from the init `SystemMessage`
5. Emits A2A events: `submitted` → `working` → `TaskArtifactUpdateEvent` → `completed`

**`ClaudeSessionStore`** — Bridges A2A's `contextId` (which groups related tasks) to the Claude Agent SDK's `session_id` (which resumes a context window). This enables multi-turn conversations that preserve Claude's full context across requests.

### Event Mapping

| Claude SDK message | A2A event |
|---|---|
| Start of query | `TaskStatusUpdateEvent(state=working)` |
| `SystemMessage(subtype="init")` | Session ID captured for future turns |
| `can_use_tool` callback fires | `TaskStatusUpdateEvent(state=input_required)` with approval DataParts |
| User approves/denies (next message) | Resolves pending approval, query continues |
| `ResultMessage.result` | `TaskArtifactUpdateEvent` with text |
| Iterator exhausted | `TaskStatusUpdateEvent(state=completed, final=True)` |
| Exception raised | `TaskStatusUpdateEvent(state=failed, final=True)` |

## Human-in-the-Loop (HITL)

Enable tool approval gates so users can approve or deny tool usage from the kagent dashboard:

```python
app = KAgentApp(
    options=ClaudeAgentOptions(
        # Don't pre-approve dangerous tools — let HITL handle them
        allowed_tools=["Read", "Glob", "Grep"],
    ),
    agent_card=agent_card,
    config=config,
    enable_hitl=True,  # Enable HITL
)
```

### How it works

When `enable_hitl=True`, tools **not** listed in `allowed_tools` trigger the approval flow:

```
1. User: "Delete all temp files"
2. Claude decides to use Bash("rm -rf /tmp/data/*")
3. Bash is not in allowed_tools → can_use_tool callback fires
4. Executor emits TaskStatusUpdateEvent(state=input_required)
   with DataPart containing tool name, args, and confirmation ID
5. kagent dashboard renders an approval card
6. User clicks Approve or Deny
7. kagent sends follow-up message with decision
8. Executor resolves the pending approval
9. Claude continues (or adjusts if denied)
```

### HITL round-trip protocol

**Approval request** (emitted by executor as DataPart):
```json
{
  "name": "adk_request_confirmation",
  "id": "<confirmation_uuid>",
  "args": {
    "originalFunctionCall": {
      "name": "Bash",
      "args": {"command": "rm -rf /tmp/data/*"},
      "id": "<tool_use_id>"
    },
    "toolConfirmation": {
      "hint": "Tool 'Bash' requires approval before execution.",
      "confirmed": false
    }
  }
}
```

**User response** (sent as DataPart in follow-up message):
```json
{"decision_type": "approve"}
```
or
```json
{"decision_type": "reject", "rejection_reason": "Too dangerous"}
```
or batch:
```json
{
  "decision_type": "batch",
  "decisions": {"<tool_use_id>": "approve", "<tool_use_id_2>": "reject"},
  "rejection_reasons": {"<tool_use_id_2>": "Not authorized"}
}
```

### Multiple approvals

Claude may request multiple tools in sequence. Each triggers a separate `input_required` pause. The executor handles this by keeping the Claude query alive in a background task while waiting for each approval.

### Without HITL

When `enable_hitl=False` (default), the executor uses the simpler direct-streaming path. Tools listed in `allowed_tools` are auto-approved by the Claude SDK. Tools not listed will be denied by the SDK's default permission mode unless you set `permission_mode="bypassPermissions"` on your options.

## Deployment

### Prerequisites

- A Kubernetes cluster with [kagent](https://kagent.dev) installed
- An Anthropic API key
- Access to a container registry

### Build and Push

```bash
# Authenticate with GitHub Container Registry
echo $GITHUB_TOKEN | docker login ghcr.io -u ganttastic --password-stdin

# Build and push
./deploy/build-and-push.sh
# Or with a specific tag:
./deploy/build-and-push.sh v0.1.0
```

### Deploy to Kubernetes

1. **Seal your API key** and update `deploy/k8s/deployment.yaml`:

```bash
# Create the sealed secret from your API key
echo -n "sk-ant-..." | kubectl create secret generic anthropic-credentials \
  --namespace=kagent --from-file=api-key=/dev/stdin --dry-run=client -o yaml \
  | kubeseal --format yaml > /tmp/sealed.yaml

# Copy the encryptedData.api-key value into deploy/k8s/deployment.yaml
```

2. **Apply the manifests:**

```bash
kubectl apply -f deploy/k8s/deployment.yaml
```

This creates:
- `Secret` — Anthropic API key
- `Deployment` — The agent container with health probes
- `Service` — ClusterIP service on port 8080
- `Agent` CRD — Registers the agent with kagent as a BYO type

3. **Verify:**

```bash
# Check the pod is running
kubectl -n kagent get pods -l app=claude-agent

# Check logs
kubectl -n kagent logs -l app=claude-agent

# Verify agent registration
kubectl -n kagent get agents
```

### Kubernetes Manifest Overview

```
deploy/
├── Dockerfile           # Multi-stage build from package source
├── build-and-push.sh   # Build + push to ghcr.io/ganttastic
├── app/
│   └── main.py         # The deployed agent application
└── k8s/
    └── deployment.yaml # Secret, Deployment, Service, Agent CRD
```

## Session Continuity

The Claude Agent SDK maintains conversation context via sessions. When kagent sends multiple messages with the same A2A `contextId`, this package:

1. On the first message: starts a fresh Claude session, captures the `session_id` from the init event
2. On subsequent messages: passes `ClaudeAgentOptions(resume=session_id)` so Claude retains its full context window (files read, analysis done, conversation history)

This is stored in-memory. For persistence across pod restarts, a Redis or controller-backed store can be substituted (not yet implemented).

## Local Development

### Run tests

```bash
cd python/packages/kagent-claude
pip install -e ".[dev]"
pytest tests/
```

### Run the example locally

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export KAGENT_URL=http://localhost:8083
export KAGENT_NAME=claude-agent
export KAGENT_NAMESPACE=default

python examples/main.py
```

Then test with an A2A request:

```bash
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
```

## Limitations (v0.1)

- **No cancellation** — `cancel()` raises `NotImplementedError` (Claude Agent SDK has no cancellation API)
- **In-memory sessions** — Session store resets on pod restart
- **In-memory HITL state** — Pending approvals are lost on pod restart
- **No push notifications** — `tasks/pushNotificationConfig` not supported

## Related

- [kagent documentation](https://kagent.dev/docs)
- [Claude Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/overview)
- [A2A Protocol specification](https://a2a-protocol.org)
- [kagent BYO agent guide](https://kagent.dev/docs/kagent/examples/a2a-byo)
- [kagent-crewai](https://github.com/kagent-dev/kagent/tree/main/python/packages/kagent-crewai) — Reference integration
