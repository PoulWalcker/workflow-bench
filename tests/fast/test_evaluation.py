import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, cast

import pytest

from workflow_bench.contracts import Criterion
from workflow_bench.data import DataError
from workflow_bench.evaluation import write_evaluation


def _read(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())


def test_proven_failure_with_complete_evidence_is_a_complete_fail(
    tmp_path: Path,
) -> None:
    write_evaluation(
        tmp_path,
        [
            {"criterion_id": "format", "status": "pass", "reason_code": "pass"},
            {"criterion_id": "total", "status": "fail", "reason_code": "wrong_total"},
        ],
    )

    assert _read(tmp_path / "evaluation.json") == {
        "verdict": "fail",
        "completeness": "complete",
        "criteria": [
            {"criterion_id": "format", "status": "pass", "reason_code": "pass"},
            {"criterion_id": "total", "status": "fail", "reason_code": "wrong_total"},
        ],
        "errors": [],
    }
    assert _read(tmp_path / "reward.json") == {"reward": 0.0}


def test_complete_pass_has_full_reward(tmp_path: Path) -> None:
    evaluation = write_evaluation(
        tmp_path, [{"criterion_id": "total", "status": "pass", "reason_code": "pass"}]
    )

    assert (evaluation["verdict"], evaluation["completeness"]) == ("pass", "complete")
    assert _read(tmp_path / "reward.json") == {"reward": 1.0}


@pytest.mark.parametrize(
    ("statuses", "errors", "verdict"),
    [
        (("pass", "unknown"), (), "unknown"),
        (("pass", "pass"), ("expected_unreadable",), "unknown"),
        # A known violation stays a failure while another criterion is unknown.
        (("fail", "unknown"), (), "fail"),
    ],
)
def test_missing_facts_leave_assessment_partial_without_reward(
    tmp_path: Path,
    statuses: tuple[Literal["pass", "fail", "unknown"], ...],
    errors: tuple[str, ...],
    verdict: str,
) -> None:
    criteria = [
        Criterion(criterion_id=f"c{index}", status=status, reason_code=status)
        for index, status in enumerate(statuses)
    ]

    write_evaluation(tmp_path, criteria, errors=errors)

    evaluation = _read(tmp_path / "evaluation.json")
    assert (evaluation["verdict"], evaluation["completeness"]) == (verdict, "partial")
    assert not (tmp_path / "reward.json").exists()


@pytest.mark.parametrize(
    "criteria",
    [
        [],
        [{"criterion_id": "total", "status": "passed", "reason_code": "pass"}],
        [{"criterion_id": "total", "status": "pass"}],
        [
            {"criterion_id": "total", "status": "pass", "reason_code": "pass"},
            {"criterion_id": "total", "status": "fail", "reason_code": "wrong"},
        ],
    ],
    ids=["empty", "unknown-status", "missing-reason", "duplicate-id"],
)
def test_invalid_criteria_are_rejected_without_output(
    tmp_path: Path, criteria: list[dict[str, str]]
) -> None:
    with pytest.raises(DataError):
        # Deliberately malformed: the helper must validate what verifiers pass.
        write_evaluation(tmp_path, cast(Sequence[Criterion], criteria))

    assert list(tmp_path.iterdir()) == []
