"""Exercise the proposal task verifier on candidate files in its image."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TASK = Path("tasks/l1-proposal-constraints")
IMAGE = "workflow-bench-agents:codex-0.162.1"


@pytest.mark.parametrize(
    ("candidate", "failed_criteria"),
    [
        pytest.param(b"word " * 250, set(), id="exactly_250_words"),
        pytest.param(b"word " * 250 + b",", {"no_comma"}, id="comma"),
        pytest.param(b"word " * 250 + b"C", {"no_letter_c"}, id="uppercase_c"),
        pytest.param(b"word " * 249, {"min_250_words"}, id="exactly_249_words"),
        pytest.param(
            b"", {"answer_file", "no_comma", "no_letter_c", "min_250_words"}, id="empty"
        ),
        pytest.param(
            b"\xff",
            {"answer_file", "no_comma", "no_letter_c", "min_250_words"},
            id="invalid_utf8",
        ),
        pytest.param(
            None,
            {"answer_file", "no_comma", "no_letter_c", "min_250_words"},
            id="missing",
        ),
    ],
)
def test_strict_criteria(
    tmp_path: Path, candidate: bytes | None, failed_criteria: set[str]
) -> None:
    """The image verifier distinguishes strict violations and unusable files."""
    output = tmp_path / "output"
    output.mkdir()
    if candidate is not None:
        (output / "response.md").write_bytes(candidate)
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
        for criterion_id in ("answer_file", "no_comma", "no_letter_c", "min_250_words")
    }
    if "answer_file" in failed_criteria:
        assert [item["reason_code"] for item in evaluation["criteria"][1:]] == [
            "no_answer"
        ] * 3
