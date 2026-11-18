# Multi-stage build: compile deps, then slim runtime.
FROM python:3.12-slim AS builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-prod.txt && \
    pip install --no-cache-dir -e .

FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages/ /usr/local/lib/python3.12/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/
COPY --from=builder /app/src/ /app/src/
COPY config/ /app/config/
COPY pyproject.toml /app/

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

EXPOSE 8701

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8701/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "stock_agents.api.main:app", "--host", "0.0.0.0", "--port", "8701"]
