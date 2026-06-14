FROM python:3.12-slim

WORKDIR /app

# Install build tools needed by asyncpg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir ".[serve,mcp]"

EXPOSE 8765

CMD ["approvalml", "serve"]
