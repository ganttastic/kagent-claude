FROM python:3.12-slim
WORKDIR /app

# Install git (needed for pip to resolve git+ dependencies of kagent-core)
RUN apt-get update && apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

# Copy the package source and install from local.
# When published to PyPI, this can be replaced with: pip install kagent-claude
COPY python/packages/kagent-claude /tmp/kagent-claude
RUN pip install --no-cache-dir --pre /tmp/kagent-claude && \
    rm -rf /tmp/kagent-claude

# Default env vars — override in your Agent CRD or docker run.
ENV CLAUDE_TOOLS="Bash,Read,Write,Edit,Glob,Grep" \
    CLAUDE_MAX_TURNS="25" \
    CLAUDE_TIMEOUT="300" \
    CLAUDE_STREAMING="true" \
    CLAUDE_HITL="false" \
    AGENT_PORT="8080" \
    AGENT_TRACING="true"

EXPOSE 8080

# Use the built-in server entrypoint — no custom Python needed.
CMD ["kagent-claude-server"]
