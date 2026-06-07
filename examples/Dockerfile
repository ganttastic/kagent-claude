# Dockerfile for custom programmatic agents.
#
# Use this when you need features the golden image can't provide:
# MCP servers, custom hooks, custom session stores, etc.
#
# For most use cases, use the published golden image instead:
#   ghcr.io/ganttastic/kagent-claude:latest
#
# Build:
#   docker build -t my-custom-agent -f examples/Dockerfile examples/
FROM python:3.12-slim
WORKDIR /app

RUN pip install --no-cache-dir --pre \
    "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"

# Copy your custom agent entrypoint
COPY custom_config.py main.py

CMD ["python", "main.py"]
