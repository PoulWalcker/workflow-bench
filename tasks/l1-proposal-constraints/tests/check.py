"""Assess the collected proposal against its four criteria."""

import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError, read_bytes
from workflow_bench.evaluation import write_evaluation

ANSWER_PATH = Path("/work/output/response.md")
VERIFIER_DIR = Path("/logs/verifier")


def main() -> None:
    """Write the independent evaluation and print a safe summary."""
    started = time.monotonic()
    answer, answer_status = _read_answer()
    criteria: list[Criterion] = [
        {
            "criterion_id": "answer_file",
            "status": "pass" if answer is not None else "fail",
            "reason_code": answer_status,
        }
    ]
    for criterion_id, follows_rule in (
        ("no_comma", answer is not None and not re.search(r"\,", answer)),
        ("no_letter_c", answer is not None and answer.lower().count("c") < 1),
        (
            "min_250_words",
            answer is not None and len(re.findall(r"\w+", answer)) >= 250,
        ),
    ):
        criteria.append(
            {
                "criterion_id": criterion_id,
                "status": "pass" if follows_rule else "fail",
                "reason_code": "no_answer"
                if answer is None
                else "pass"
                if follows_rule
                else "rule_failed",
            }
        )
    evaluation = write_evaluation(VERIFIER_DIR, criteria)
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    sys.stdout.write(
        f"at={timestamp} phase=verifier result={evaluation['verdict']} "
        f"duration={time.monotonic() - started:.3f}s criteria={len(criteria)}\n"
    )


def _read_answer() -> tuple[str | None, str]:
    """Return bounded UTF-8 content or a safe failure reason."""
    if not ANSWER_PATH.exists() and not ANSWER_PATH.is_symlink():
        return None, "missing_answer"
    try:
        answer = read_bytes(ANSWER_PATH, "response.md").decode("utf-8")
    except (DataError, OSError, UnicodeDecodeError):
        return None, "invalid_answer"
    if not answer:
        return None, "empty_answer"
    return answer, "pass"


if __name__ == "__main__":
    main()
