# Shared harness image: task environment images build FROM it.
# Base images, the Debian package and the Codex CLI are pinned here only.

# Build-only stage: npm resolves Codex's platform package; only its output is kept.
# Sapiens requires Codex >= 0.156.1.
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

# The named context is a git archive prepared by build.sh, never the source worktree.
ARG SAPIENS_REVISION
LABEL org.workflow-bench.sapiens.revision="${SAPIENS_REVISION}"
COPY --from=sapiens / /opt/sapiens/
RUN test "$(cat /opt/sapiens/REVISION)" = "${SAPIENS_REVISION}" \
    && printf '/opt/sapiens\n' > /usr/local/lib/python3.12/site-packages/sapiens.pth \
    && python -m sapiens --help > /dev/null

# Task verifiers run in images built FROM this one and call the Workflow Bench
# evaluation helper. Its direct imports, jsonschema and referencing, and their
# dependencies are installed at the versions locked in uv.lock.
RUN --mount=type=bind,from=project,source=uv.lock,target=/tmp/uv.lock \
    --mount=type=bind,source=lock_requirements.py,target=/tmp/lock_requirements.py \
    python /tmp/lock_requirements.py /tmp/uv.lock jsonschema referencing \
        > /tmp/helper-requirements.txt \
    && PIP_ROOT_USER_ACTION=ignore pip install --no-cache-dir --no-deps \
        --disable-pip-version-check -r /tmp/helper-requirements.txt \
    && rm /tmp/helper-requirements.txt
COPY --from=project src/workflow_bench/__init__.py src/workflow_bench/contracts.py \
    src/workflow_bench/data.py src/workflow_bench/evaluation.py \
    /usr/local/lib/python3.12/site-packages/workflow_bench/
COPY --from=project src/workflow_bench/resources/wire.schema.json \
    /usr/local/lib/python3.12/site-packages/workflow_bench/resources/
RUN python -c "import workflow_bench.evaluation"
