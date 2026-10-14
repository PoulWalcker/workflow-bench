#!/bin/sh
set -eu
python3 - <<'PY'
from pathlib import Path
from workflow_bench.data import DataError
from workflow_bench.evaluation import write_evaluation
from workflow_bench.window import read_window

root = Path('/window-evidence')
try:
    facts = read_window(root)
except DataError:
    facts = None
if (
    facts is None
    or facts.status != 'completed'
    or len(facts.drops) != 2
    or len(facts.snapshots) != 2
):
    status, reason = 'unknown', 'window_incomplete'
else:
    first = root / facts.snapshots[0].directory
    second = root / facts.snapshots[1].directory
    timed = (
        all(
            abs(item.actual_offset_sec - item.planned_offset_sec) <= 5
            for item in (*facts.drops, *facts.snapshots)
        )
        and not list(first.rglob('a.txt')) and not list(first.rglob('b.txt'))
        and bool(list(second.rglob('a.txt'))) and not list(second.rglob('b.txt'))
    )
    worked = all((Path('/work/output') / f'{name}.txt').exists() for name in ('a', 'b'))
    status, reason = ('pass', 'pass') if timed and worked else ('fail', 'window_result')
write_evaluation(Path('/logs/verifier'), [{'criterion_id': 'window', 'status': status, 'reason_code': reason}])
PY
