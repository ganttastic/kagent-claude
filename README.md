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
# Install from GitHub (not yet published to PyPI)
pip install "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"
```

Or add to your `requirements.txt`:

```
kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude
```

Or in `pyproject.toml` dependencies:

```toml
dependencies = [
    "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude",
]
```

Requires Python 3.10+. The `claude-agent-sdk` and `kagent-core` dependencies are installed automatically.

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
        url="http://localhost:8080/",
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
    config=KAgentConfig(),  # reads KAGENT_URL, KAGENT_NAME, KAGENT_NAMESPACE from env
)

if __name__ == "__main__":
    app.run(port=8080)
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key from [console.anthropic.com](https://console.anthropic.com) |
| `KAGENT_URL` | Auto-injected | kagent controller URL (injected by kagent for BYO agents) |
| `KAGENT_NAME` | Auto-injected | Agent name matching the Agent CRD (injected by kagent) |
| `KAGENT_NAMESPACE` | Auto-injected | Kubernetes namespace (injected by kagent) |

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

### ClaudeExecutorConfig

Controls runtime behavior of the executor:

```python
from kagent.claude import ClaudeExecutorConfig

ClaudeExecutorConfig(
    execution_timeout=300.0,  # Max seconds before query is killed (default: 300)
    enable_streaming=True,    # Stream tool calls/results to dashboard (default: True)
    enable_hitl=False,        # Require user approval for tool use (default: False)
)
```

| Field | Default | Description |
|-------|---------|-------------|
| `execution_timeout` | `300.0` | Maximum seconds a query runs before timeout. Set higher (600+) for complex coding tasks. |
| `enable_streaming` | `True` | Stream intermediate events (tool calls, results) to the kagent dashboard in real-time. |
| `enable_hitl` | `False` | When enabled, tool invocations pause for user approval via the dashboard. |

### KAgentApp Constructor

```python
KAgentApp(
    options: ClaudeAgentOptions,                    # What Claude can do
    agent_card: AgentCard,                          # A2A identity (name, skills, capabilities)
    config: KAgentConfig = None,                    # Platform config (auto from env vars)
    executor_config: ClaudeExecutorConfig = None,   # Runtime behavior (timeout, streaming, HITL)
    tracing: bool = True,                           # Enable OpenTelemetry tracing
)
```

### HITL (Human-in-the-Loop) Flow

When `enable_hitl=True`, tool executions pause for user approval:

1. Claude decides to use a tool (e.g., `Bash: rm -rf /tmp/data`)
2. The executor emits `input_required` with tool details as a DataPart
3. The kagent dashboard shows a confirmation dialog
4. User approves → tool executes, Claude continues
5. User denies → Claude receives the rejection reason and adapts

See `examples/hitl.py` for a complete runnable example with curl commands.

### Ask-User Answers

When Claude asks the user a question (via the dashboard), the user's response
is extracted from the `ask_user_answers` DataPart and passed back to Claude
as the next prompt on the resumed session. This happens automatically — no
configuration needed.

## Architecture

### Package Structure

```
python/packages/kagent-claude/src/kagent/claude/
├── __init__.py          # Public exports: KAgentApp, ClaudeAgentExecutor, ClaudeExecutorConfig
├── _a2a.py              # KAgentApp — assembles FastAPI server with A2A routes
├── _converters.py       # Claude SDK messages → A2A DataParts for streaming
├── _error_mappings.py   # Exception classification (rate_limit, auth, timeout, etc.)
├── _executor.py         # ClaudeAgentExecutor — A2A AgentExecutor implementation
├── _hitl.py             # HITL bridge (approval flow + ask_user_answers)
├── _metadata_utils.py   # Namespaced metadata builders for A2A events
├── _session_store.py    # Maps A2A contextId to Claude session_id
└── _tracing.py          # OpenTelemetry span helpers
```

### Key Components

**`KAgentApp`** — The public entrypoint. Wires together the executor, task store, request handler, and A2A application into a runnable FastAPI server. Follows the same pattern as `kagent-crewai` and `kagent-langgraph`.

**`ClaudeAgentExecutor`** — Implements the A2A `AgentExecutor` interface. On each `execute()` call:
1. Extracts user text from the A2A message (or `ask_user_answers` if present)
2. Looks up any existing Claude session for the context
3. Calls `query(prompt, options)` with `resume` set if resuming, wrapped in `asyncio.wait_for()` for timeout
4. Streams intermediate events (tool calls, tool results) to the dashboard via `_converters.py`
5. Classifies errors via `_error_mappings.py` for user-friendly failure messages
6. Emits A2A events: `submitted` → `working` → (streaming events) → `artifact` → `completed`

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
from kagent.claude import ClaudeExecutorConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        # Don't pre-approve dangerous tools — let HITL handle them
        allowed_tools=["Read", "Glob", "Grep"],
    ),
    agent_card=agent_card,
    executor_config=ClaudeExecutorConfig(enable_hitl=True),
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

### Local Development

No Kubernetes or Docker required. Just install the package and run your agent:

```bash
pip install "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"
```

Create your agent (`main.py`):

```python
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import KAgentApp

app = KAgentApp(
    options=ClaudeAgentOptions(allowed_tools=["Bash", "Read", "Glob"]),
    agent_card=AgentCard(
        name="my-agent",
        description="My Claude agent",
        url="http://localhost:8080/",
        version="1.0.0",
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text"],
        default_output_modes=["text"],
        skills=[],
    ),
)

if __name__ == "__main__":
    app.run(port=8080)
```

Run it:

```bash
ANTHROPIC_API_KEY=sk-ant-... \
KAGENT_URL=http://localhost:8083 \
KAGENT_NAME=my-agent \
KAGENT_NAMESPACE=default \
python main.py
```

Send a message:

```bash
curl -X POST http://localhost:8080/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0", "id": "1", "method": "message/send",
    "params": {
      "message": {
        "messageId": "msg-001", "role": "user",
        "parts": [{"kind": "text", "text": "What files are in the current directory?"}]
      }
    }
  }'
```

### Deploy to Kubernetes

#### Prerequisites

- A Kubernetes cluster with [kagent](https://kagent.dev) installed
- An Anthropic API key
- A container image with your agent

#### Build your container image

Create a `Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir --pre \
    "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"

COPY main.py .
CMD ["python", "main.py"]
```

Build and push:

```bash
docker build -t ghcr.io/your-org/my-claude-agent:latest .
docker push ghcr.io/your-org/my-claude-agent:latest
```

> **Note:** The `deploy/` directory in this repo contains a reference Dockerfile and build script if you prefer to build from source.

#### Apply the Agent CRD

1. **Create the API key secret:**

```bash
kubectl create secret generic kagent-anthropic \
  --namespace=kagent \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...
```

2. **Apply the Agent CRD:**

```yaml
# agent.yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: my-claude-agent
  namespace: kagent
spec:
  description: My Claude-powered agent
  type: BYO
  byo:
    deployment:
      image: ghcr.io/your-org/my-claude-agent:latest
      env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: kagent-anthropic
              key: ANTHROPIC_API_KEY
```

```bash
kubectl apply -f agent.yaml
```

The kagent controller creates the Deployment and Service automatically. The `KAGENT_URL`, `KAGENT_NAME`, and `KAGENT_NAMESPACE` env vars are injected by the controller.

3. **Verify:**

```bash
kubectl -n kagent get agents
kubectl -n kagent get pods -l kagent.dev/agent=my-claude-agent
kubectl -n kagent logs -l kagent.dev/agent=my-claude-agent
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

## Limitations (v0.2)

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
