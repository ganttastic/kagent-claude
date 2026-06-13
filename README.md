# kagent-claude

[![CI](https://github.com/ganttastic/kagent-claude/actions/workflows/ci.yml/badge.svg)](https://github.com/ganttastic/kagent-claude/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/ganttastic/kagent-claude/graph/badge.svg)](https://codecov.io/gh/ganttastic/kagent-claude)
[![PyPI](https://img.shields.io/pypi/v/kagent-claude)](https://pypi.org/project/kagent-claude/)
[![Python](https://img.shields.io/pypi/pyversions/kagent-claude)](https://pypi.org/project/kagent-claude/)
[![License](https://img.shields.io/github/license/ganttastic/kagent-claude)](https://github.com/ganttastic/kagent-claude/blob/main/LICENSE)
[![GHCR](https://img.shields.io/badge/container-ghcr.io-blue?logo=github)](https://ghcr.io/ganttastic/kagent-claude)

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

## Quick Start

### Zero-Code Deployment (Recommended)

Deploy a Claude agent with no Python and no Docker builds — just a YAML file:

```bash
# 1. Create your API key secret
kubectl create secret generic kagent-anthropic \
  --namespace=kagent \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# 2. Deploy
kubectl apply -f examples/agent.yaml
```

The published golden image (`ghcr.io/ganttastic/kagent-claude`) is fully
configurable via environment variables. Customize model, tools, system prompt,
timeouts, HITL, MCP servers, security posture, and skills directly in the Agent CRD:

```yaml
apiVersion: kagent.dev/v1alpha2
kind: Agent
metadata:
  name: my-claude-agent
  namespace: kagent
spec:
  description: My Claude agent
  type: BYO
  byo:
    deployment:
      image: ghcr.io/ganttastic/kagent-claude:latest
      env:
        - name: ANTHROPIC_API_KEY
          valueFrom:
            secretKeyRef:
              name: kagent-anthropic
              key: ANTHROPIC_API_KEY
        - name: CLAUDE_MODEL
          value: "claude-sonnet-4-5"
        - name: CLAUDE_TOOLS
          value: "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch"
        - name: CLAUDE_SYSTEM_PROMPT
          value: "You are a senior engineer. Explain your reasoning."
        - name: CLAUDE_MCP_SERVERS
          value: '{"fetch": {"type": "http", "url": "http://mcp-server/mcp"}}'
        - name: CLAUDE_SKILLS
          value: "true"
```

See [`examples/`](examples/) for ready-to-use CRD files and the full
[env var reference](examples/README.md#environment-variables).

### Programmatic Usage

For advanced use cases (custom hooks, custom session stores, complex
agent logic), write Python:

```python
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from claude_agent_sdk import ClaudeAgentOptions
from kagent.claude import KAgentApp
from kagent.core import KAgentConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        mcp_servers={
            "my-server": {"command": "npx", "args": ["@my-org/my-mcp-server"]},
        },
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
    config=KAgentConfig(),
)

if __name__ == "__main__":
    app.run(port=8080)
```

### Installation (for programmatic usage)

```bash
pip install "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"
```

Requires Python 3.10+. The `claude-agent-sdk` and `kagent-core` dependencies are installed automatically.

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
    model="claude-sonnet-4-5",          # Which model to use
    fallback_model="claude-haiku-4",    # Auto-failover if primary unavailable
    tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebSearch", "WebFetch"],
    allowed_tools=["Read", "Glob", "Grep"],  # Auto-approved (others need HITL approval)
    disallowed_tools=["WebSearch"],     # Block specific tools entirely
    system_prompt="You are a helpful coding assistant.",
    max_turns=10,
    permission_mode="acceptEdits",      # Security posture for tool execution
    max_budget_usd=5.0,                 # Cost cap per execution
    effort="high",                      # Reasoning depth (low/medium/high/xhigh/max)
    add_dirs=["/data/shared"],          # Additional directory access
    strict_mcp_config=True,             # Ignore project .mcp.json files
    mcp_servers={
        "my-server": {
            "command": "npx",
            "args": ["@my-org/my-mcp-server"],
        }
    },
)
```

#### Golden Image Environment Variables

When using the golden image, all SDK options are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_MODEL` | *(SDK default)* | Claude model (e.g., `claude-sonnet-4-5`, `claude-opus-4-5`) |
| `CLAUDE_FALLBACK_MODEL` | *(none)* | Fallback model if primary is unavailable |
| `CLAUDE_TOOLS` | `Bash,Read,Write,Edit,Glob,Grep` | Comma-separated tools available to Claude |
| `CLAUDE_ALLOWED_TOOLS` | *(same as `CLAUDE_TOOLS`)* | Tools auto-approved without prompting (for HITL scenarios) |
| `CLAUDE_DISALLOWED_TOOLS` | *(none)* | Comma-separated tools to block entirely |
| `CLAUDE_SYSTEM_PROMPT` | *(none)* | System prompt for Claude |
| `CLAUDE_MAX_TURNS` | `25` | Max conversation turns |
| `CLAUDE_PERMISSION_MODE` | *(SDK default)* | `default`, `acceptEdits`, `bypassPermissions`, `plan`, `dontAsk` |
| `CLAUDE_MAX_BUDGET_USD` | *(unlimited)* | Maximum budget in USD per execution |
| `CLAUDE_EFFORT` | *(SDK default)* | Reasoning effort: `low`, `medium`, `high`, `xhigh`, `max` |
| `CLAUDE_ADD_DIRS` | *(none)* | Comma-separated additional directory paths |
| `CLAUDE_STRICT_MCP_CONFIG` | `false` | Only use MCP servers from `CLAUDE_MCP_SERVERS` |
| `CLAUDE_MCP_SERVERS` | *(none)* | JSON object of MCP server configs |
| `CLAUDE_ALLOWED_MCP_TOOLS` | *(all)* | MCP tool patterns to auto-approve |
| `CLAUDE_TIMEOUT` | `300` | Execution timeout in seconds |
| `CLAUDE_STREAMING` | `true` | Stream tool calls/results to dashboard |
| `CLAUDE_HITL` | `false` | Require user approval for tool use |
| `CLAUDE_HITL_TIMEOUT` | `600` | Timeout when HITL enabled |
| `CLAUDE_SKILLS` | `false` | Enable skill discovery |
| `CLAUDE_SKILLS_FILTER` | *(all)* | Comma-separated skill names to enable |
| `CLAUDE_CWD` | `/app` | Working directory for skill discovery |

### ClaudeAgentExecutorConfig

Controls runtime behavior of the executor:

```python
from kagent.claude import ClaudeAgentExecutorConfig

ClaudeAgentExecutorConfig(
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
    executor_config: ClaudeAgentExecutorConfig = None,   # Runtime behavior (timeout, streaming, HITL)
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
├── __init__.py          # Public exports: KAgentApp, ClaudeAgentExecutor, ClaudeAgentExecutorConfig
├── server.py            # Golden image entrypoint — env-configurable server
├── _a2a.py              # KAgentApp — assembles FastAPI server with A2A routes
├── _converters.py       # Claude SDK messages → A2A DataParts for streaming
├── _error_mappings.py   # Exception classification (rate_limit, auth, timeout, etc.)
├── _executor.py         # ClaudeAgentExecutor — A2A AgentExecutor implementation
├── _hitl.py             # HITL bridge (approval flow + ask_user_answers)
├── _metadata_utils.py   # Namespaced metadata builders for A2A events
├── _session_store.py    # SessionStore protocol + in-memory LRU implementation
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
from kagent.claude import ClaudeAgentExecutorConfig

app = KAgentApp(
    options=ClaudeAgentOptions(
        # Don't pre-approve dangerous tools — let HITL handle them
        allowed_tools=["Read", "Glob", "Grep"],
    ),
    agent_card=agent_card,
    executor_config=ClaudeAgentExecutorConfig(enable_hitl=True),
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

### Using the Golden Image (Recommended)

The published image `ghcr.io/ganttastic/kagent-claude` is a fully
env-configurable Claude agent. No Python, no Docker builds required.

1. **Create the API key secret:**

```bash
kubectl create secret generic kagent-anthropic \
  --namespace=kagent \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...
```

2. **Apply the Agent CRD:**

```bash
kubectl apply -f examples/agent.yaml
```

3. **Verify:**

```bash
kubectl -n kagent get agents
kubectl -n kagent get pods -l kagent.dev/agent=claude-agent
kubectl -n kagent logs -l kagent.dev/agent=claude-agent
```

The kagent controller creates the Deployment and Service automatically. The
`KAGENT_URL`, `KAGENT_NAME`, and `KAGENT_NAMESPACE` env vars are injected
by the controller. See [`examples/README.md`](examples/README.md) for the
full env var reference.

### Custom Image (for hooks, custom session stores, etc.)

If you need features the golden image can't express (custom hooks,
custom session stores, complex startup logic), write a Python
entrypoint and build a custom image:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir --pre \
    "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"
COPY main.py .
CMD ["python", "main.py"]
```

```bash
docker build -t ghcr.io/your-org/my-claude-agent:latest .
docker push ghcr.io/your-org/my-claude-agent:latest
```

Then reference your image in the Agent CRD instead of the golden image.

## Session Continuity

The Claude Agent SDK maintains conversation context via sessions. When kagent sends multiple messages with the same A2A `contextId`, this package:

1. On the first message: starts a fresh Claude session, captures the `session_id` from the init event
2. On subsequent messages: passes `ClaudeAgentOptions(resume=session_id)` so Claude retains its full context window (files read, analysis done, conversation history)

This is stored in-memory with LRU eviction (default 1024 sessions). For
persistence across pod restarts, implement the `SessionStore` protocol with
a Redis or controller-backed backend:

```python
from kagent.claude import SessionStore

class RedisSessionStore:
    """Example custom session store."""
    def get(self, context_id: str) -> str | None: ...
    def set(self, context_id: str, claude_session_id: str) -> None: ...
    def delete(self, context_id: str) -> None: ...
```

## Local Development

### Run the golden image server locally

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export KAGENT_URL=http://localhost:8083
export KAGENT_NAME=claude-agent
export KAGENT_NAMESPACE=default

# Using the console script
kagent-claude-server

# Or as a Python module
python -m kagent.claude.server
```

### Run an example

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export KAGENT_URL=http://localhost:8083
export KAGENT_NAME=claude-agent
export KAGENT_NAMESPACE=default

python examples/basic.py
```

### Run tests

```bash
cd python/packages/kagent-claude
pip install -e ".[dev]"
pytest tests/
```

### Test with an A2A request

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

## Limitations

- **No cancellation** — `cancel()` raises `NotImplementedError` (Claude Agent SDK has no cancellation API)
- **In-memory sessions** — Session store uses LRU eviction (1024 sessions); resets on pod restart. Implement `SessionStore` protocol for persistence.
- **In-memory HITL state** — Pending approvals are lost on pod restart
- **No push notifications** — `tasks/pushNotificationConfig` not supported
- **Skills require ConfigMap mount** — Claude SDK skills can't be defined via env vars alone; they need filesystem artifacts mounted into the container

## Related

- [kagent documentation](https://kagent.dev/docs)
- [Claude Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/overview)
- [A2A Protocol specification](https://a2a-protocol.org)
- [kagent BYO agent guide](https://kagent.dev/docs/kagent/examples/a2a-byo)
- [kagent-crewai](https://github.com/kagent-dev/kagent/tree/main/python/packages/kagent-crewai) — Reference integration
