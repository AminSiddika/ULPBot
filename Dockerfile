FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app

COPY src/ ./src/
COPY data/ ./data/
COPY downloads/ ./downloads/

RUN mkdir -p /app/logs

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "-m", "src.main"]
