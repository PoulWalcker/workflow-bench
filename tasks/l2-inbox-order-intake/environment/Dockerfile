FROM workflow-bench-agents:codex-0.162.1
WORKDIR /work
COPY drops/ /opt/window/drops/
COPY schedule.json /opt/window/schedule.json
COPY manifest.json /window-evidence/manifest.json
RUN mkdir -p /work/inbox /work/output
