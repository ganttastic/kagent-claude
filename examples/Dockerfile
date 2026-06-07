FROM python:3.12-slim
WORKDIR /app

# Install kagent-claude from git
# --pre is needed for opentelemetry pre-release instrumentation packages
RUN pip install --no-cache-dir --pre \
    "kagent-claude @ git+https://github.com/ganttastic/kagent-claude.git#subdirectory=python/packages/kagent-claude"

# Copy the agent app (change this to your own main.py)
COPY basic.py main.py

CMD ["python", "main.py"]
