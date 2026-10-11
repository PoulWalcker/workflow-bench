#!/bin/sh
set -eu
test ! -w /bench/input
python - <<'CHECK'
import os
from pathlib import Path
assert os.getuid() != 0
assert not Path("/solution").exists()
assert not Path("/var/run/docker.sock").exists()
assert not Path("/usr/local/lib/node_modules/n8n").exists()
for path in Path("/bench/input").rglob("*"):
    assert not os.access(path, os.W_OK)
CHECK
python /tests/verify.py --input-dir /bench/input --output /logs/verifier/evaluation.json --state-schema /app/telegram/state.schema.json
