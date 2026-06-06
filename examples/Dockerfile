FROM python:3.12-slim
WORKDIR /app

# Install kagent-claude from source (not yet published to PyPI)
# --pre is needed because kagent-core depends on opentelemetry-instrumentation-fastapi
# which only publishes pre-release versions (0.52b0, 0.63b1, etc.)
COPY python/packages/kagent-claude/ /app/kagent-claude/
RUN pip install --no-cache-dir --pre /app/kagent-claude/

# Copy the example app
COPY examples/main.py .

CMD ["python", "main.py"]
