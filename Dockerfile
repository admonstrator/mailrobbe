FROM node:22-slim AS frontend

WORKDIR /frontend

# Dependencies first, so source changes do not invalidate this layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./
RUN npm run build

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so code changes do not invalidate this layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY src ./src
RUN uv sync --frozen --no-dev

COPY --from=frontend /frontend/dist ./frontend/dist
COPY docker/entrypoint.sh /usr/local/bin/mailrobbe-entrypoint

# Runs as root on purpose: the MBOX directory is a read-only bind mount with the host's file
# permissions, which an unprivileged container user often cannot read.
EXPOSE 8000
ENTRYPOINT ["mailrobbe-entrypoint"]
CMD ["mailrobbe", "serve"]
