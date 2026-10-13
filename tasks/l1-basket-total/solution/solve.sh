#!/bin/sh
# Proves the task is solvable from the public instruction alone.
set -eu
python3 - <<'SOLVE'
import json
from pathlib import Path

basket = [(3, 45), (1, 230), (2, 119), (1, 575)]
answer = {
    "item_count": sum(quantity for quantity, _ in basket),
    "total_cents": sum(quantity * price for quantity, price in basket),
}
Path("/work/output/answer.json").write_text(json.dumps(answer))
SOLVE
