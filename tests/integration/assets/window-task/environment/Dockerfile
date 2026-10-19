FROM workflow-bench-agents:codex-0.162.1
WORKDIR /work
COPY schedule.json /opt/window/schedule.json
COPY drops /opt/window/drops
COPY manifest.json /window-evidence/manifest.json
RUN mkdir -p /work/output /work/inbox
