"""Exercise the table join verifier on candidate files in its image."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

TASK = Path("tasks/l1-table-join")
IMAGE = "workflow-bench-agents:codex-0.162.1"
CORRECT = {
    "zip": "eaRWRFfT5Wg",
    "address": "am9yrWhMHrw",
    "hospital_subtype": "RKRCNpVVdoc",
}
CRITERION_IDS = (
    "answer_file",
    "map_zip",
    "map_address",
    "map_hospital_subtype",
    "no_extra_mapping",
)


@pytest.mark.parametrize(
    ("candidate", "failed_criteria"),
    [
        pytest.param(json.dumps(CORRECT).encode(), set(), id="exact_mapping"),
        pytest.param(
            json.dumps({**CORRECT, "zip": "am9yrWhMHrw"}).encode(),
            {"map_zip"},
            id="wrong_zip",
        ),
        pytest.param(
            json.dumps({**CORRECT, "address": "eaRWRFfT5Wg"}).encode(),
            {"map_address"},
            id="wrong_address",
        ),
        pytest.param(
            json.dumps({**CORRECT, "hospital_subtype": "eaRWRFfT5Wg"}).encode(),
            {"map_hospital_subtype"},
            id="wrong_subtype",
        ),
        pytest.param(
            json.dumps({**CORRECT, "city": "LB1c5bVtloU"}).encode(),
            {"no_extra_mapping"},
            id="extra_pair",
        ),
        pytest.param(
            b"{'zip': 'eaRWRFfT5Wg'}",
            set(CRITERION_IDS),
            id="python_dict_text",
        ),
    ],
)
def test_join_criteria(
    tmp_path: Path, candidate: bytes, failed_criteria: set[str]
) -> None:
    """The image verifier reports each mapping error independently."""
    output = tmp_path / "output"
    output.mkdir()
    (output / "join_mapping.json").write_bytes(candidate)
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
        for criterion_id in CRITERION_IDS
    }
    assert evaluation["verdict"] == ("fail" if failed_criteria else "pass")
