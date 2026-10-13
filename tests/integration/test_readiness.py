"""`wb check-task` readiness through real `harbor run` oracle and no-op controls."""

import json
import shutil
from pathlib import Path

import pytest

from workflow_bench.cli import main

# A verifier that passes whatever the agent did: the no-op control must expose it.
ALWAYS_PASS_TEST = """#!/bin/sh
set -eu
exec python3 -c '
from pathlib import Path
from workflow_bench.evaluation import write_evaluation
write_evaluation(
    Path("/logs/verifier"),
    [{"criterion_id": "answer", "status": "pass", "reason_code": "pass"}],
)
'
"""


def _check_task(
    task: Path, jobs_dir: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict]:
    status = main(["check-task", str(task), "--jobs-dir", str(jobs_dir)])
    return status, json.loads(capsys.readouterr().out)


def test_trivial_task_is_ready(
    trivial_task: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status, report = _check_task(trivial_task, tmp_path, capsys)

    assert status == 0
    assert report["reasons"] == []
    assert [(run["agent"], run["result"]) for run in report["runs"]] == [
        ("oracle", "pass"),
        ("nop", "fail"),
    ]


def test_task_whose_no_op_passes_is_not_ready(
    trivial_task: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken"
    shutil.copytree(trivial_task, broken, ignore=shutil.ignore_patterns("__pycache__"))
    (broken / "tests" / "test.sh").write_text(ALWAYS_PASS_TEST)

    status, report = _check_task(broken, tmp_path / "jobs", capsys)

    assert status == 1
    assert report["reasons"] == ["nop_not_fail:pass"]
