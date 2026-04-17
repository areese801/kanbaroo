FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock* README.md ./
COPY src/ ./src/
COPY packages/ ./packages/

RUN uv sync --all-packages --no-dev

EXPOSE 8080

CMD ["uv", "run", "--no-dev", "kanberoo-api"]
