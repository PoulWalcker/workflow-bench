"""Assess the collected sequence answer against its private expectation."""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_json
from workflow_bench.evaluation import write_evaluation

ANSWER_PATH = Path("/work/output/answer.json")
EXPECTED_PATH = Path("/tests/expected/answer.json")
VERIFIER_DIR = Path("/logs/verifier")


def main() -> None:
    """Write the independent evaluation and print a safe summary."""
    started = time.monotonic()
    expected = read_json(EXPECTED_PATH, "expected")
    if not isinstance(expected, dict) or type(expected.get("answer")) is not int:
        raise DataError("invalid_expected", "expected")
    answer, answer_status = _read_answer()
    if answer is None:
        value_status, value_reason = "fail", "no_answer"
    elif answer != expected["answer"]:
        value_status, value_reason = "fail", "wrong_value"
    else:
        value_status, value_reason = "pass", "pass"
    criteria: list[Criterion] = [
        {
            "criterion_id": "answer_file",
            "status": "pass" if answer is not None else "fail",
            "reason_code": answer_status,
        },
        {
            "criterion_id": "answer_value",
            "status": value_status,
            "reason_code": value_reason,
        },
    ]
    evaluation = write_evaluation(VERIFIER_DIR, criteria)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sys.stdout.write(
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"duration={time.monotonic() - started:.3f}s criteria={len(criteria)}\n"
    )


def _read_answer() -> tuple[int | None, str]:
    """Return a bounded JSON answer, or a safe failure reason."""
    if not ANSWER_PATH.exists() and not ANSWER_PATH.is_symlink():
        return None, "missing_answer"
    try:
        content = read_json(ANSWER_PATH, "answer")
    except (DataError, OSError):
        return None, "invalid_answer"
    if not isinstance(content, dict) or set(content) != {"answer"}:
        return None, "invalid_answer"
    value = content["answer"]
    if type(value) is not int or not 0 <= value <= 999:
        return None, "invalid_answer"
    return value, "pass"


if __name__ == "__main__":
    main()
