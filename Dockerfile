FROM python:3.12-slim
WORKDIR /app

# Install kagent-claude with all dependencies.
# --pre is needed for opentelemetry pre-release instrumentation packages.
RUN pip install --no-cache-dir --pre \
    "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"

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
