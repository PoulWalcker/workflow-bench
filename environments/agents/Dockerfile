# Shared harness image: task environment images build FROM it.
# Base images, the Debian package and the Codex CLI are pinned here only.

# Build-only stage: npm resolves Codex's platform package; only its output is kept.
# Codex 0.162.1 was the latest stable release when pinned and meets Sapiens' >= 0.156.1.
FROM node:22.23.3-trixie-slim@sha256:154ba2f4d6fec323d28e4f4bb86bba4677f1223391a1979cf521304e03a98dfa AS codex
RUN npm install --global --prefix /opt/codex --no-audit --no-fund @openai/codex@0.162.1

FROM python:3.12.15-slim-trixie@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
RUN apt-get update \
    && apt-get install -y --no-install-recommends procps=2:4.0.4-9 \
    && rm -rf /var/lib/apt/lists/*
# The Codex launcher is a Node script; the official Node binary needs only glibc/libstdc++.
COPY --from=codex /usr/local/bin/node /usr/local/bin/node
COPY --from=codex /opt/codex /opt/codex
RUN ln -s /opt/codex/bin/codex /usr/local/bin/codex && codex --version && ps --version
