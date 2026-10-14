"""Exercise the rational-sequence task verifier on candidate files in its image."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TASK = Path("tasks/l1-rational-sequence")
IMAGE = "workflow-bench-agents:codex-0.162.1"


@pytest.mark.parametrize(
    ("candidate", "failed_criteria"),
    [
        pytest.param(b'{"answer": 248}', set(), id="correct_answer"),
        pytest.param(b'{"answer": 247}', {"answer_value"}, id="wrong_answer"),
        pytest.param(
            b'{"answer": "248"}', {"answer_file", "answer_value"}, id="string"
        ),
        pytest.param(
            b'{"answer": true}', {"answer_file", "answer_value"}, id="boolean"
        ),
        pytest.param(
            b'{"answer": 1000}', {"answer_file", "answer_value"}, id="out_of_range"
        ),
        pytest.param(
            b'{"other": 248}', {"answer_file", "answer_value"}, id="missing_key"
        ),
        pytest.param(
            b'{"answer": 248, "extra": 1}',
            {"answer_file", "answer_value"},
            id="extra_key",
        ),
    ],
)
def test_answer_criteria(
    tmp_path: Path, candidate: bytes | None, failed_criteria: set[str]
) -> None:
    """The image verifier evaluates the submitted answer criteria."""
    output = tmp_path / "output"
    output.mkdir()
    if candidate is not None:
        (output / "answer.json").write_bytes(candidate)
    logs = tmp_path / "logs"
    logs.mkdir()
    staged_tests = tmp_path / "tests"
    shutil.copytree(TASK / "tests", staged_tests)

    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--mount",
            f"type=bind,src={staged_tests},dst=/tests,readonly",
            "--mount",
            f"type=bind,src={output},dst=/work/output,readonly",
            "--mount",
            f"type=bind,src={logs},dst=/logs/verifier",
            IMAGE,
            "sh",
            "/tests/test.sh",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    evaluation = json.loads((logs / "evaluation.json").read_text())
    statuses = {item["criterion_id"]: item["status"] for item in evaluation["criteria"]}
    assert statuses == {
        criterion_id: "fail" if criterion_id in failed_criteria else "pass"
        for criterion_id in ("answer_file", "answer_value")
    }
