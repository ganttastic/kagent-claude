FROM python:3.12-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV ANTHROPIC_API_KEY=""
ENV KAGENT_URL="http://kagent-controller:8083"
ENV KAGENT_NAME="claude-agent"
ENV KAGENT_NAMESPACE="kagent"

CMD ["python", "main.py"]
