FROM workflow-bench-agents:codex-0.162.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        extundelete=0.2.4-3+b3 \
        foremost=1.5.7-11+b1 \
        sleuthkit=4.12.1+dfsg-3 \
        e2fsprogs=1.47.2-3+b12 \
        binutils=2.44-3 \
        zip=3.0-15+deb13u1 \
        unzip=6.0-29+deb13u1 \
    && rm -rf /var/lib/apt/lists/*

COPY setup.sh seeded_bytes.py /app/
RUN bash /app/setup.sh \
    && rm /app/setup.sh /app/seeded_bytes.py

WORKDIR /app
