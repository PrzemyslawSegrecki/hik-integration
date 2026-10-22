FROM node:25-alpine AS web
WORKDIR /app

COPY package.json package-lock.json tsconfig.base.json ./
COPY apps/web/package.json apps/web/package.json
RUN npm ci

COPY apps/web apps/web
RUN npm run build

FROM python:3.13-alpine AS deps
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /bin/uv
WORKDIR /app/apps/server
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY apps/server/pyproject.toml apps/server/uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.13-alpine AS runtime
WORKDIR /app/apps/server
ENV PATH=/app/apps/server/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8090

COPY --from=deps /app/apps/server/.venv .venv
COPY apps/server/hik_server hik_server
COPY --from=web /app/apps/web/dist public

RUN adduser -D -H -u 1000 app
USER app
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- "http://127.0.0.1:${PORT}/api/health" >/dev/null || exit 1

CMD ["python", "-m", "hik_server"]
