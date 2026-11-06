# The API image (07/O1): built once, promoted by digest, never rebuilt per environment. One image runs every role:
#   docker run IMAGE api | worker | migrate | config-check      (src/skeleton_proof_e_next_ai/run.py)
# Build from the repository root (the context .dockerignore keeps secrets and caches out, 12/N10):
#   docker build -f apps/api/Dockerfile --build-arg BUILD_SHA=$(git rev-parse HEAD) -t skeleton-proof-e-next-ai-api .
# Base images are pinned by digest (13/V3), each at least 7 days old when pinned (13/V4) unless a security fix needs it
# sooner: Python 3.14.10 and Node 26.13.0 (both rebuilt 2026-11-05) fix CVE-2026-115557 (CPython, Critical) and
# CVE-2026-109518 (apt, High), which Grype found in the earlier bases on the first CI run on GitHub. Renovate moves them.

FROM ghcr.io/astral-sh/uv:0.13.6@sha256:af22a52f5eafef3d78e551599d405c02df61919d18028f0cea8eda93bc9986d0 AS uv

FROM python:3.14.10-slim-trixie@sha256:af8a5aa14780025dbfbcfbc81bd8a91ebd87711dd5b0f48ed71090949dd7cb1d AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app/apps/api
# Dependencies first, from the lockfile only, so the layer is reused until the lock changes; no dev tools (13/V3).
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14.10-slim-trixie@sha256:af8a5aa14780025dbfbcfbc81bd8a91ebd87711dd5b0f48ed71090949dd7cb1d AS runtime
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home --home-dir /app app
# Where a deployed API keeps uploads: a mounted volume, owned by the app user (ops/deploy/compose-host/compose.yaml).
RUN install -d -o app -g app /data/uploads
WORKDIR /app/apps/api
COPY --from=build /app/.venv /app/.venv
# Only what runs (07/O1): the source, its migrations, the business configuration and the governed AI data (12/N4).
COPY apps/api/alembic.ini ./
COPY apps/api/config ./config
COPY apps/api/src ./src
COPY ai /app/ai
ENV PATH=/app/.venv/bin:$PATH PYTHONPATH=/app/apps/api/src PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# The build SHA travels with the image and is shown on /health (02/A12, README #15).
ARG BUILD_SHA=unknown
ENV APP_BUILD_SHA=$BUILD_SHA
LABEL org.opencontainers.image.revision=$BUILD_SHA org.opencontainers.image.title="skeleton-proof-e-next-ai-api"
USER app
EXPOSE 8000
ENTRYPOINT ["python", "-m", "skeleton_proof_e_next_ai.run"]
CMD ["api"]
