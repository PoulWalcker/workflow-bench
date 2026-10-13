"""Assess the collected result against this task's private criteria."""

from pathlib import Path

from workflow_bench.contracts import Criterion
from workflow_bench.evaluation import write_evaluation

RESULT_DIR = Path("/work/output")
EXPECTED_DIR = Path("/tests/expected")
VERIFIER_DIR = Path("/logs/verifier")


def main() -> None:
    # One entry per task-owned criterion: "fail" only for a proven violation,
    # "unknown" when the facts needed to decide are missing or untrusted.
    criteria: list[Criterion] = [
        {"criterion_id": "todo", "status": "unknown", "reason_code": "not_implemented"}
    ]
    write_evaluation(VERIFIER_DIR, criteria)


if __name__ == "__main__":
    main()
