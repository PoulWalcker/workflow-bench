"""Assess a bounded grid answer against the private solution."""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_json
from workflow_bench.evaluation import write_evaluation

ANSWER_PATH = Path("/work/output/solution.json")
EXPECTED_PATH = Path("/tests/expected/solution.json")
VERIFIER_DIR = Path("/logs/verifier")


def _read_candidate(expected: dict) -> tuple[dict | None, str]:
    if not ANSWER_PATH.exists() and not ANSWER_PATH.is_symlink():
        return None, "missing_answer"
    try:
        candidate = read_json(ANSWER_PATH, "solution.json")
    except (DataError, OSError):
        return None, "invalid_answer"
    if not isinstance(candidate, dict) or set(candidate) != set(expected):
        return None, "wrong_keys"
    for house, expected_values in expected.items():
        values = candidate[house]
        if not isinstance(values, dict) or set(values) != set(expected_values):
            return None, "wrong_keys"
        if not all(isinstance(value, str) for value in values.values()):
            return None, "invalid_values"
    return candidate, "pass"


def main() -> None:
    """Write one format Criterion and one Criterion per house."""
    started = time.monotonic()
    expected = read_json(EXPECTED_PATH, "expected/solution.json")
    candidate, answer_reason = _read_candidate(expected)
    criteria: list[Criterion] = [
        {
            "criterion_id": "answer_file",
            "status": "pass" if candidate is not None else "fail",
            "reason_code": answer_reason,
        }
    ]
    for house, expected_values in expected.items():
        is_correct = candidate is not None and all(
            candidate[house][attribute].strip().casefold() == value.strip().casefold()
            for attribute, value in expected_values.items()
        )
        if is_correct:
            reason_code = "pass"
        elif candidate is None:
            reason_code = "no_answer"
        else:
            reason_code = "wrong_house"
        criteria.append(
            {
                "criterion_id": house.lower().replace(" ", "_"),
                "status": "pass" if is_correct else "fail",
                "reason_code": reason_code,
            }
        )
    evaluation = write_evaluation(VERIFIER_DIR, criteria)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sys.stdout.write(
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"duration={time.monotonic() - started:.3f}s criteria={len(criteria)}\n"
    )


if __name__ == "__main__":
    main()
