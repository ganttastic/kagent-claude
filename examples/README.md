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

Use these when you need features that env vars can't express: custom
hooks, custom session stores, or complex agent logic.

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

If you've written a custom Python entrypoint with hooks or a custom session store:

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
| `CLAUDE_MODEL` | *(SDK default)* | Claude model to use (e.g., `claude-sonnet-4-5`, `claude-opus-4-5`) |
| `CLAUDE_FALLBACK_MODEL` | *(none)* | Fallback model if primary is unavailable |
| `CLAUDE_TOOLS` | `Bash,Read,Write,Edit,Glob,Grep` | Comma-separated tools available to Claude |
| `CLAUDE_ALLOWED_TOOLS` | *(same as `CLAUDE_TOOLS`)* | Tools auto-approved without prompting (for HITL) |
| `CLAUDE_DISALLOWED_TOOLS` | *(none)* | Comma-separated tools to block entirely (removed from model context) |
| `CLAUDE_SYSTEM_PROMPT` | *(none)* | System prompt for Claude |
| `CLAUDE_MAX_TURNS` | `25` | Max turns before Claude stops |
| `CLAUDE_PERMISSION_MODE` | *(SDK default)* | Permission mode: `default`, `acceptEdits`, `bypassPermissions`, `plan`, `dontAsk` |
| `CLAUDE_MAX_BUDGET_USD` | *(unlimited)* | Maximum budget in USD per execution |
| `CLAUDE_EFFORT` | *(SDK default)* | Reasoning effort: `low`, `medium`, `high`, `xhigh`, `max` |
| `CLAUDE_ADD_DIRS` | *(none)* | Comma-separated absolute paths for additional directory access |
| `CLAUDE_MCP_SERVERS` | *(none)* | JSON object of MCP server configs (see [MCP Servers](#mcp-servers)) |
| `CLAUDE_ALLOWED_MCP_TOOLS` | *(all from configured servers)* | Comma-separated MCP tool patterns to auto-approve (see [MCP Servers](#mcp-servers)) |
| `CLAUDE_STRICT_MCP_CONFIG` | `false` | Only use MCP servers from `CLAUDE_MCP_SERVERS`, ignore all other sources |

### Skills

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_SKILLS` | `false` | Enable Claude Agent SDK skill discovery |
| `CLAUDE_SKILLS_FILTER` | *(all)* | Comma-separated skill names to enable (default: all discovered) |
| `CLAUDE_CWD` | `/app` | Working directory for skill discovery |

Mount skill files into the container at `/app/.claude/skills/<name>/SKILL.md`
using a ConfigMap. See [Skills via ConfigMap](#skills-via-configmap) below.

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
| `AGENT_SKILLS` | *(general skill)* | JSON array of AgentCard skill objects (display metadata, not Claude SDK skills) |
| `AGENT_PORT` | `8080` | Server listen port |
| `AGENT_TRACING` | `true` | Enable OpenTelemetry tracing |

### Platform (Auto-Injected)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Claude API key (from Secret) |
| `KAGENT_URL` | kagent controller URL (injected by controller) |
| `KAGENT_NAME` | Agent name matching the CRD (injected by controller) |
| `KAGENT_NAMESPACE` | Kubernetes namespace (injected by controller) |

### AgentCard Skills JSON Format

The `AGENT_SKILLS` env var populates the A2A AgentCard (display metadata in the
kagent dashboard). This is separate from Claude Agent SDK skills.

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

### MCP Servers

Configure MCP servers via the `CLAUDE_MCP_SERVERS` env var. This is a JSON
object where each key is a server name and the value is its config.

**Stdio servers** (local subprocess):

```json
{
  "github": {
    "command": "npx",
    "args": ["@modelcontextprotocol/server-github"],
    "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
  }
}
```

**HTTP/SSE servers** (remote endpoints):

```json
{
  "fetch": {
    "type": "http",
    "url": "http://mcp-server.default.svc.cluster.local/mcp"
  },
  "secure-api": {
    "type": "sse",
    "url": "https://api.example.com/mcp/sse",
    "headers": {"Authorization": "Bearer $API_TOKEN"}
  }
}
```

**Environment variable interpolation**: Values containing `$VAR` or `${VAR}`
are resolved against the pod's environment at startup. This lets you keep
secrets in Kubernetes Secrets and reference them in MCP config:

```yaml
env:
  - name: GITHUB_TOKEN
    valueFrom:
      secretKeyRef:
        name: github-token
        key: token
  - name: CLAUDE_MCP_SERVERS
    value: |
      {"github": {"command": "npx",
        "args": ["@modelcontextprotocol/server-github"],
        "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}}}
```

Use `$$` for a literal `$` if needed.

**MCP tool permissions**: By default, all tools from all configured MCP servers
are auto-approved (`mcp__<server-name>__*`). Use `CLAUDE_ALLOWED_MCP_TOOLS` to
restrict which tools are available:

```yaml
- name: CLAUDE_ALLOWED_MCP_TOOLS
  value: "mcp__github__list_issues,mcp__github__search_issues"
```

### Skills via ConfigMap

The Claude Agent SDK discovers skills from `.claude/skills/*/SKILL.md` files.
In the golden image, mount skill files via Kubernetes ConfigMap:

**1. Create a ConfigMap with your skill files:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: claude-agent-skills
  namespace: kagent
data:
  my-skill.md: |
    ---
    name: my-skill
    description: Does something useful when asked about X.
    ---

    # My Skill

    Instructions for Claude when this skill is triggered...
```

**2. Mount and enable in the Agent CRD:**

```yaml
spec:
  byo:
    deployment:
      image: ghcr.io/ganttastic/kagent-claude:latest
      volumes:
        - name: skills
          configMap:
            name: claude-agent-skills
      volumeMounts:
        - name: skills
          mountPath: /app/.claude/skills/my-skill/SKILL.md
          subPath: my-skill.md
      env:
        - name: CLAUDE_SKILLS
          value: "true"
```

Each skill needs its own `volumeMount` with `subPath` pointing to the
ConfigMap key. The mount path must follow the pattern
`/app/.claude/skills/<skill-name>/SKILL.md`.

Claude automatically discovers and invokes skills based on their
`description` field when the user's request matches.
