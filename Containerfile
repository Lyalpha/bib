# bib — BPASS-in-Browser
# Multi-stage build. Works with both podman and docker:
#   podman build -t bib .
#   docker build -t bib -f Containerfile .

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cache-friendly), then the project itself.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------------------
FROM python:3.15-slim-bookworm

RUN groupadd -r bib && useradd -r -g bib -d /app bib

WORKDIR /app
COPY --from=builder --chown=bib:bib /app/.venv /app/.venv
COPY --chown=bib:bib src /app/src
COPY --chown=bib:bib data/filters /app/data/filters
COPY --chown=bib:bib branding.yaml /app/branding.yaml
COPY --chown=bib:bib scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    BIB_FILTERS_DIR=/app/data/filters

USER bib
EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["serve"]
