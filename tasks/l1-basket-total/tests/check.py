"""Assess the collected basket answer against the private expectation."""

from pathlib import Path

from workflow_bench.contracts import Criterion, JsonValue
from workflow_bench.data import DataError, read_json
from workflow_bench.evaluation import write_evaluation

ANSWER_PATH = Path("/work/output/answer.json")
EXPECTED_PATH = Path("/tests/expected/answer.json")
VERIFIER_DIR = Path("/logs/verifier")
FIELDS = ("item_count", "total_cents")


def main() -> None:
    expected = read_json(EXPECTED_PATH, "expected")
    if not isinstance(expected, dict):
        raise DataError("invalid_expected", "expected")
    answer, answer_status = _read_answer()
    criteria: list[Criterion] = [
        {
            "criterion_id": "answer_file",
            "status": "pass" if answer is not None else "fail",
            "reason_code": answer_status,
        }
    ]
    for field in FIELDS:
        criteria.append(_field_criterion(field, answer, expected[field]))
    write_evaluation(VERIFIER_DIR, criteria)


def _read_answer() -> tuple[dict[str, JsonValue] | None, str]:
    """Return the answer object, or None with the safe reason it is unusable."""
    if not ANSWER_PATH.exists() and not ANSWER_PATH.is_symlink():
        return None, "missing_answer"
    try:
        answer = read_json(ANSWER_PATH, "answer")
    except DataError:
        return None, "invalid_answer"
    if (
        not isinstance(answer, dict)
        or set(answer) != set(FIELDS)
        or any(type(answer[field]) is not int for field in FIELDS)
    ):
        return None, "invalid_answer"
    return answer, "pass"


def _field_criterion(
    field: str, answer: dict[str, JsonValue] | None, expected: JsonValue
) -> Criterion:
    if answer is None:
        return {"criterion_id": field, "status": "fail", "reason_code": "no_answer"}
    if answer[field] != expected:
        return {"criterion_id": field, "status": "fail", "reason_code": "wrong_value"}
    return {"criterion_id": field, "status": "pass", "reason_code": "pass"}


if __name__ == "__main__":
    main()
