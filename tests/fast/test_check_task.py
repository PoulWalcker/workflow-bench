"""Structure rejections of `wb check-task`; readiness runs are integration controls."""

import json
import shutil
from pathlib import Path

import pytest

from workflow_bench.cli import main

TRIVIAL_TASK = Path(__file__).resolve().parents[2] / "tasks" / "l1-basket-total"


@pytest.fixture
def task_dir(tmp_path: Path) -> Path:
    copy = tmp_path / "task"
    shutil.copytree(TRIVIAL_TASK, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


def _check_task(task: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, dict]:
    status = main(["check-task", str(task), "--jobs-dir", str(task.parent / "jobs")])
    return status, json.loads(capsys.readouterr().out)


def test_missing_mandatory_file_is_rejected_by_name(
    task_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (task_dir / "tests" / "test.sh").unlink()

    status, report = _check_task(task_dir, capsys)

    assert status == 1
    assert report["ready"] is False
    assert report["reasons"] == ["missing:tests/test.sh"]
    assert report["runs"] == []
    assert not (task_dir.parent / "jobs").exists()


def test_unexpected_top_level_file_is_rejected_by_name(
    task_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (task_dir / "notes.md").write_text("draft\n")

    status, report = _check_task(task_dir, capsys)

    assert status == 1
    assert report["reasons"] == ["unexpected:notes.md"]
    assert report["runs"] == []


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ('level = "L1"\n', "", "invalid:metadata.level"),
        ('horizon = "single"\n', 'horizon = "daily"\n', "invalid:metadata.horizon"),
        ("[agent]\ntimeout_sec = 600.0\n", "", "missing:agent.timeout_sec"),
        (
            'environment_mode = "separate"\n',
            'environment_mode = "shared"\n',
            "invalid:verifier.environment_mode",
        ),
        ('schema_version = "1.4"\n', "schema_version = \n", "invalid:task.toml"),
    ],
    ids=["level", "horizon", "agent-timeout", "shared-verifier", "unparsable"],
)
def test_task_config_rule_violation_is_rejected_by_name(
    task_dir: Path,
    capsys: pytest.CaptureFixture[str],
    old: str,
    new: str,
    reason: str,
) -> None:
    config = task_dir / "task.toml"
    assert old in config.read_text()
    config.write_text(config.read_text().replace(old, new))

    status, report = _check_task(task_dir, capsys)

    assert status == 1
    assert report["reasons"] == [reason]
    assert not (task_dir.parent / "jobs").exists()
