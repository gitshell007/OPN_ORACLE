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

# XDG_CACHE_HOME en /tmp: el rootfs es read-only en producción y fontconfig
# necesita un directorio de caché escribible (el de sistema se precalienta
# con fc-cache en build).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    XDG_CACHE_HOME=/tmp/.cache

# pango/harfbuzz/fontconfig + fuentes: runtime nativo de WeasyPrint (PDF de informes).
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libfontconfig1 \
        fonts-dejavu-core \
        fonts-liberation \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 oracle \
    && useradd --system --uid 10001 --gid oracle --home-dir /app oracle \
    && install --directory --owner=oracle --group=oracle --mode=0750 /var/lib/oracle-storage \
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
