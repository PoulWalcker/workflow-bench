"""Native Harbor controls for the shared observation-window helper."""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

from workflow_bench.comparison import compare
from workflow_bench.window import read_window

ASSET = Path(__file__).parent / "assets/window-task"


@pytest.fixture(scope="module")
def run_root() -> Path:
    """Keep every native job in one unique location outside Desktop."""
    configured = os.environ.get("WB_R02_RUN_ROOT")
    if configured:
        root = Path(configured)
        if not str(root).startswith("/tmp/wb-r-02-"):
            pytest.fail("WB_R02_RUN_ROOT must be under /tmp/wb-r-02-*")
        root.mkdir(parents=True, exist_ok=True)
        return root
    return Path(tempfile.mkdtemp(prefix="wb-r-02-", dir="/tmp"))


@pytest.mark.integration
@pytest.mark.parametrize(
    ("agent", "short_hook", "expected"),
    [("oracle", False, "pass"), ("nop", False, "fail"), ("oracle", True, "unknown")],
    ids=["oracle", "nop", "hook-timeout"],
)
def test_window_control(
    run_root: Path, agent: str, short_hook: bool, expected: str
) -> None:
    """Collect a real window, or retain incomplete evidence after hook timeout."""
    case = run_root / ("hook-timeout" if short_hook else agent)
    task = case / "task"
    shutil.copytree(ASSET, task)
    if short_hook:
        task_config = task / "task.toml"
        task_config.write_text(
            task_config.read_text().replace("timeout_sec = 122.0", "timeout_sec = 5.0")
        )
    jobs = case / "jobs"
    config = {
        "job_name": "control",
        "jobs_dir": str(jobs),
        "quiet": True,
        "n_concurrent_trials": 1,
        "environment": {
            "import_path": "workflow_bench.harbor:DeadlineDockerEnvironment",
            "kwargs": {"cleanup_timeout_sec": 60},
        },
        "tasks": [{"path": str(task)}],
    }
    config_path = case / "job.yaml"
    config_path.write_text(yaml.safe_dump(config))
    environment = dict(os.environ)
    for key in (
        "CODEX_AUTH_JSON_PATH",
        "CODEX_FORCE_AUTH_JSON",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        environment.pop(key, None)
    with (case / "harbor.log").open("w") as log:
        completed = subprocess.run(
            ["harbor", "run", "-c", str(config_path), "--agent", agent],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=300,
            check=False,
        )
    assert completed.returncode == 0, (case / "harbor.log").read_text()
    job = jobs / "control"
    report = compare([job])
    (case / "compare.json").write_text(json.dumps(report, indent=2) + "\n")
    assert [trial["outcome"] for trial in report["pairs"][0]["trials"]] == [expected]
    evidence = next(job.glob("*/artifacts/window-evidence"))
    facts = read_window(evidence)
    if short_hook:
        assert facts.status != "completed"
        evaluation = json.loads(
            next(job.glob("*/verifier/evaluation.json")).read_text()
        )
        assert evaluation["criteria"][0]["reason_code"] == "window_incomplete"
    else:
        assert facts.status == "completed"
        assert len(facts.drops) == len(facts.snapshots) == 2
        assert all(
            abs(item.actual_offset_sec - item.planned_offset_sec) <= 5
            for item in (*facts.drops, *facts.snapshots)
        )
    trial_log = next(job.glob("*/trial.log")).read_text()
    assert trial_log.count("cleanup result=confirmed") >= 2
