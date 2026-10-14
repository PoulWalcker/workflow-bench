FROM workflow-bench-agents:codex-0.162.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        sqlite3=3.46.1-7+deb13u2 \
        xxd=2:9.1.1230-2 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY main.db /app/main.db
COPY main.db-wal.encrypted /app/main.db-wal
