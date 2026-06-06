FROM python:3.12-slim
WORKDIR /app

# Install the package from source
# --pre is needed because kagent-core depends on opentelemetry-instrumentation-fastapi>=0.52.0
# but the package only publishes pre-release versions (0.52b0, 0.63b1, etc.)
COPY python/packages/kagent-claude/ /app/kagent-claude/
RUN pip install --no-cache-dir --pre /app/kagent-claude/

# Copy the app
COPY deploy/app/main.py .

CMD ["python", "main.py"]
