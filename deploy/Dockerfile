FROM python:3.12-slim
WORKDIR /app

# Install the package from source
COPY python/packages/kagent-claude/ /app/kagent-claude/
RUN pip install --no-cache-dir /app/kagent-claude/

# Copy the app
COPY deploy/app/main.py .

CMD ["python", "main.py"]
