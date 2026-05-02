FROM python:3.12-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/

RUN mkdir -p data

# 既定では bot worker として起動する。
# - docker-compose.yml の `bot` / `api` サービスは `command:` で上書き
# - Railway は railway.toml / railway.api.toml の startCommand で上書き
CMD ["python", "-m", "src.main"]
