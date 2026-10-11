# syntax=docker/dockerfile:1
# One image for the API (default command) and the arq worker (compose overrides the command).

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so code changes do not reinstall them. Dev dependencies are left out.
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY app ./app

# Non-root user. /data/storage is the storage volume mount point; a new named volume copies this
# directory's ownership, so the app can write to it.
RUN useradd --create-home --uid 10001 formpilot \
    && mkdir -p /data/storage \
    && chown -R formpilot:formpilot /data
USER formpilot

EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
