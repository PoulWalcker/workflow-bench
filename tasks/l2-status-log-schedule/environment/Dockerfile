FROM workflow-bench-agents:codex-0.162.1
WORKDIR /work
COPY data/ /work/data/
COPY schedule.json /opt/window/schedule.json
COPY manifest.json /window-evidence/manifest.json
RUN mkdir -p /work/output
