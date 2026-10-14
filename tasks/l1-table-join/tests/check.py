"""Assess the collected table join mapping against private expected pairs."""

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_json
from workflow_bench.evaluation import write_evaluation

ANSWER_PATH = Path("/work/output/join_mapping.json")
EXPECTED_PATH = Path("/tests/expected/join_mapping.json")
VERIFIER_DIR = Path("/logs/verifier")
PAIR_KEYS = ("zip", "address", "hospital_subtype")


def main() -> None:
    """Write an exact mapping evaluation and print a safe summary."""
    started = time.monotonic()
    mapping, answer_status = _read_mapping()
    expected = _read_expected()
    criteria: list[Criterion] = [
        {
            "criterion_id": "answer_file",
            "status": "pass" if mapping is not None else "fail",
            "reason_code": answer_status,
        }
    ]
    for key in PAIR_KEYS:
        is_correct = mapping is not None and mapping.get(key) == expected[key]
        if mapping is None:
            reason_code = "no_answer"
        elif is_correct:
            reason_code = "pass"
        else:
            reason_code = "wrong_mapping"
        criteria.append(
            {
                "criterion_id": f"map_{key}",
                "status": "pass" if is_correct else "fail",
                "reason_code": reason_code,
            }
        )
    has_no_extra_mapping = mapping is not None and mapping.keys() <= expected.keys()
    if mapping is None:
        extra_reason = "no_answer"
    elif has_no_extra_mapping:
        extra_reason = "pass"
    else:
        extra_reason = "extra_mapping"
    criteria.append(
        {
            "criterion_id": "no_extra_mapping",
            "status": "pass" if has_no_extra_mapping else "fail",
            "reason_code": extra_reason,
        }
    )
    evaluation = write_evaluation(VERIFIER_DIR, criteria)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sys.stdout.write(
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"duration={time.monotonic() - started:.3f}s criteria={len(criteria)}\n"
    )


def _read_mapping() -> tuple[dict[str, str] | None, str]:
    """Return a bounded JSON string mapping or a safe failure reason."""
    if not ANSWER_PATH.exists() and not ANSWER_PATH.is_symlink():
        return None, "missing_answer"
    try:
        answer = read_json(ANSWER_PATH, "join_mapping.json")
    except (DataError, OSError):
        return None, "invalid_answer"
    if not isinstance(answer, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in answer.items()
    ):
        return None, "invalid_answer"
    return answer, "pass"


def _read_expected() -> dict[str, str]:
    """Load the verifier-owned mapping, rejecting corrupt private expectations."""
    raw = read_json(EXPECTED_PATH, "expected/join_mapping.json")
    if not isinstance(raw, dict) or set(raw) != set(PAIR_KEYS):
        raise ValueError("invalid_expected_mapping")
    expected: dict[str, str] = {}
    for key in PAIR_KEYS:
        value = raw[key]
        if not isinstance(value, str):
            raise ValueError("invalid_expected_mapping")
        expected[key] = value
    return expected


if __name__ == "__main__":
    main()
