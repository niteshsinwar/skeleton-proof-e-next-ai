# The web image (07/O1): built once, promoted by digest. It runs Next.js's standalone server, the same server the e2e
# lane tests (03/F24). Build from the repository root (the context .dockerignore keeps secrets and caches out):
#   docker build -f apps/web/Dockerfile --build-arg BUILD_SHA=$(git rev-parse HEAD) -t skeleton-proof-e-next-ai-web .
# The base is pinned by digest (13/V3). 26.13.0 (rebuilt 2026-11-05) is taken inside the 7-day cooldown by the security
# path (13/V4): it fixes CVE-2026-109518 (apt, High), which Grype found in the 26.12.1 base on the first CI run on GitHub.
# Renovate moves it; package.json `engines` allows the whole 26 line.

FROM node:26.13.0-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS build
RUN npm install --global --ignore-scripts --no-fund --no-audit pnpm@11.28.9
WORKDIR /app/apps/web
# Dependencies from the lockfile only, so the layer is reused until it changes; pnpm-workspace.yaml carries the
# cooldown and the install-script policy (13/V4).
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile --loglevel=error
COPY packages/contracts /app/packages/contracts
COPY apps/web ./
# The release travels with the bundle, so every error report names the build it came from (03/F48).
ARG BUILD_SHA=unknown
ENV NEXT_PUBLIC_RELEASE=$BUILD_SHA NEXT_TELEMETRY_DISABLED=1
# The browser's Sentry DSN is public and inlined at build (one DSN for every environment, so the image is built once).
ARG SENTRY_DSN=""
ENV NEXT_PUBLIC_SENTRY_DSN=$SENTRY_DSN
RUN pnpm gen:api && pnpm build

FROM node:26.13.0-trixie-slim@sha256:5adad64f9a1fca2d51972caa65983634c8a774eb300d72b20f7f2a0f60368072 AS runtime
# The server only runs `node server.js`: npm and the other global packages go, and with them the advisories in npm's
# own bundled dependencies (undici, brace-expansion: Grype, High) that this image would otherwise ship (05/SG13).
RUN rm -rf /usr/local/lib/node_modules /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
# Only the traced standalone output and its static assets (07/O1): no sources, tests or dev dependencies.
COPY --from=build --chown=node:node /app/apps/web/.next/standalone ./
ARG BUILD_SHA=unknown
LABEL org.opencontainers.image.revision=$BUILD_SHA org.opencontainers.image.title="skeleton-proof-e-next-ai-web"
USER node
EXPOSE 3000
CMD ["node", "server.js"]
