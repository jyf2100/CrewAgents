FROM python:3.11-slim

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

# Install build deps
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

# Copy project files from root context
COPY pyproject.toml ./
COPY hermes_orchestrator/ hermes_orchestrator/
COPY swarm/ swarm/

# Install with orchestrator extras
RUN pip install --no-cache-dir -i ${PIP_INDEX_URL} -e ".[orchestrator]"

EXPOSE 8080

CMD ["uvicorn", "hermes_orchestrator.main:app", "--host", "0.0.0.0", "--port", "8080"]
