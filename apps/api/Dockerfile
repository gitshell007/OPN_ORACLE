# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.25 AS uv

FROM python:3.11-slim-bookworm AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY --from=uv /uv /uvx /bin/

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.11-slim-bookworm AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

RUN groupadd --system --gid 10001 oracle \
    && useradd --system --uid 10001 --gid oracle --home-dir /app oracle \
    && python -m pip uninstall --yes setuptools wheel \
    && python -m pip uninstall --yes pip
WORKDIR /app
COPY --from=builder --chown=oracle:oracle /app /app
COPY --chown=oracle:oracle migrations ./migrations
COPY --chown=oracle:oracle gunicorn.conf.py ./gunicorn.conf.py

USER oracle
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=2)"]

CMD ["gunicorn", "-c", "gunicorn.conf.py", "opn_oracle.wsgi:app"]
