#!/bin/sh
set -eu
nohup python3 -c '
import time
from datetime import UTC, datetime
from pathlib import Path

started = time.monotonic()
for index in range(1, 7):
    time.sleep(max(0, started + index * 120 - time.monotonic()))
    count = sum(path.is_file() and not path.is_symlink() for path in Path("/work/data").iterdir())
    with Path("/work/output/status.log").open("a") as stream:
        stream.write(f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} {count}\n")
' </dev/null >/tmp/status-reporter.log 2>&1 &
