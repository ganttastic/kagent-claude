# Examples

## Zero-Code Deployment (Recommended)

The published golden image is fully configurable via environment variables.
No Python, no Docker builds — just apply a YAML file.

```bash
# 1. Create your API key secret
kubectl create secret generic kagent-anthropic \
  --namespace=kagent \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# 2. Deploy a Claude agent
kubectl apply -f examples/agent.yaml
```

### Agent CRD Examples

| File | Description |
|------|-------------|
| `agent.yaml` | Standard Claude agent with coding tools |
| `agent-hitl.yaml` | Claude agent with human-in-the-loop approval |

Customize behavior by setting environment variables in the CRD — see
the [env var reference](#environment-variables) below.

## Programmatic Examples

Use these when you need features that env vars can't express: MCP servers,
custom hooks, custom session stores, or complex agent logic.

| File | Description |
|------|-------------|
| `basic.py` | Minimal programmatic agent (equivalent to golden image defaults) |
| `custom_config.py` | MCP server integration, custom system prompt, timeouts |
| `hitl.py` | Human-in-the-loop with curl round-trip examples |

### Run Locally

```bash
pip install --pre "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"

ANTHROPIC_API_KEY=sk-ant-... \
KAGENT_URL=http://localhost:8083 \
KAGENT_NAME=my-agent \
KAGENT_NAMESPACE=default \
python examples/basic.py
```

### Build a Custom Image

If you've written a custom Python entrypoint with MCP servers or hooks:

```bash
# Build using the examples Dockerfile
docker build -t ghcr.io/your-org/my-agent:latest -f examples/Dockerfile examples/
docker push ghcr.io/your-org/my-agent:latest
```

## Environment Variables

All variables are optional except `ANTHROPIC_API_KEY`.

### Claude SDK

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_TOOLS` | `Bash,Read,Write,Edit,Glob,Grep` | Comma-separated tool list |
| `CLAUDE_SYSTEM_PROMPT` | *(none)* | System prompt for Claude |
| `CLAUDE_MAX_TURNS` | `25` | Max turns before Claude stops |

### Executor

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_TIMEOUT` | `300` | Execution timeout in seconds |
| `CLAUDE_STREAMING` | `true` | Stream tool calls/results to dashboard |
| `CLAUDE_HITL` | `false` | Require user approval for tool use |
| `CLAUDE_HITL_TIMEOUT` | `600` | Timeout when HITL is enabled (overrides `CLAUDE_TIMEOUT`) |

### Agent Identity

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_NAME` | `claude-agent` | Agent card name |
| `AGENT_DESCRIPTION` | `Claude-powered agent running on kagent` | Agent card description |
| `AGENT_VERSION` | *(package version)* | Agent card version |
| `AGENT_SKILLS` | *(general skill)* | JSON array of skill objects |
| `AGENT_PORT` | `8080` | Server listen port |
| `AGENT_TRACING` | `true` | Enable OpenTelemetry tracing |

### Platform (Auto-Injected)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key (from Secret) |
| `KAGENT_URL` | kagent controller URL (injected by controller) |
| `KAGENT_NAME` | Agent name matching the CRD (injected by controller) |
| `KAGENT_NAMESPACE` | Kubernetes namespace (injected by controller) |

### Skills JSON Format

```json
[
  {
    "id": "coding",
    "name": "Code assistance",
    "description": "Read, analyze, and modify code",
    "tags": ["coding", "analysis"],
    "examples": ["Find all TODO comments", "Explain how auth works"]
  }
]
```
