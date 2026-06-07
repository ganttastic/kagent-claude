# Examples

Runnable examples showing how to build and deploy a Claude-powered kagent BYO agent.

## Local Development

```bash
# Install the package
pip install "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"

# Run any example
ANTHROPIC_API_KEY=sk-ant-... \
KAGENT_URL=http://localhost:8083 \
KAGENT_NAME=my-agent \
KAGENT_NAMESPACE=default \
python examples/basic.py
```

## Examples

| File | Description |
|------|-------------|
| `basic.py` | Minimal agent with coding tools |
| `custom_config.py` | Timeout, streaming, system prompt, and tracing options |
| `hitl.py` | Human-in-the-loop approval with curl round-trip |

## Kubernetes Deployment

| File | Description |
|------|-------------|
| `Dockerfile` | Container image for any example agent |
| `build-and-push.sh` | Build + push to a container registry |
| `agent.yaml` | Agent CRD — apply this to register with kagent |

```bash
# Build the container image (uses basic.py by default)
./examples/build-and-push.sh ghcr.io/your-org/my-claude-agent

# Create your API key secret
kubectl create secret generic kagent-anthropic \
  --namespace=kagent \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-...

# Deploy
kubectl apply -f examples/agent.yaml
```
