"""Direct Codex wiring and cessation through native Harbor jobs, without a model."""

import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest
import yaml

from workflow_bench.comparison import compare
from workflow_bench.composer import SessionSafeCodex

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/codex/job.yaml"
FAKE_CODEX = """#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
if "--version" in sys.argv:
    print("codex-cli 0.162.1")
    sys.exit(0)
assert sys.argv[1] == "exec"
private_paths = ["/tests", "/solution", "/var/run/docker.sock"]
assert not any(Path(p).exists() for p in private_paths)
assert not os.environ.get("OPENAI_API_KEY")
Path("/logs/agent/isolation-checked").write_text("yes")
answer = {"item_count": 7, "total_cents": 1178}
Path("/work/output/answer.json").write_text(json.dumps(answer))
"""


def test_fake_codex_completes_task_in_isolation(
    trivial_task: Path, tmp_path: Path
) -> None:
    task = _fake_task(trivial_task, tmp_path, FAKE_CODEX)
    job = _run_job(task, tmp_path)
    report = compare([job])
    assert [trial["outcome"] for trial in report["pairs"][0]["trials"]] == ["pass"]
    assert list(job.glob("*/agent/isolation-checked"))


def test_pinned_codex_empty_provider_is_evaluated_from_state(
    trivial_task: Path, tmp_path: Path
) -> None:
    job = _run_job(trivial_task, tmp_path)
    report = compare([job])
    assert [trial["outcome"] for trial in report["pairs"][0]["trials"]] == ["fail"]
    native = json.loads(next(job.glob("*/result.json")).read_text())
    assert native["agent_info"]["version"] == "0.162.1"
    logs = next(job.glob("*/agent/codex.txt")).read_text()
    assert "turn.started" in logs
    session = next(job.glob("*/agent/sessions/**/*.jsonl"))
    metadata = json.loads(session.read_text().splitlines()[0])["payload"]
    assert metadata["cli_version"] == "0.162.1"
    assert metadata["model_provider"] == "empty"
    agent_logs = next(job.glob("*/agent"))
    agent = SessionSafeCodex(logs_dir=agent_logs, version="0.162.1")
    trajectory = agent.convert_trajectory(agent_logs)
    assert trajectory is not None
    assert trajectory.agent.version == "0.162.1"
    assert any(
        step.source == "user"
        and isinstance(step.message, str)
        and "# Basket total" in step.message
        for step in trajectory.steps
    )


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
def test_late_child_cannot_write_after_stop(
    trivial_task: Path, tmp_path: Path, cancel: bool
) -> None:
    executable = (
        FAKE_CODEX
        + """
if os.fork() == 0:
    os.setsid()
    Path("/logs/agent/child-started").write_text(str(os.getpid()))
    time.sleep(8)
    Path("/logs/agent/late-write").write_text("escaped cancellation")
    time.sleep(120)
else:
    time.sleep(120)
"""
    )
    task = _fake_task(trivial_task, tmp_path, executable)
    job = _run_job(
        task, tmp_path, cancel=cancel, timeout_seconds=3 if not cancel else 60
    )
    assert list(job.glob("*/agent/child-started"))
    time.sleep(9)
    assert not list(job.glob("*/agent/late-write"))
    trial = next(job.glob("*/result.json")).parent.name
    project = trial.lower() + "__env"
    running = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={project}",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert running.stdout == ""


def _fake_task(source: Path, directory: Path, executable: str) -> Path:
    task = directory / "task"
    shutil.copytree(source, task, ignore=shutil.ignore_patterns("__pycache__"))
    (task / "environment/fake-codex").write_text(executable)
    with (task / "environment/Dockerfile").open("a") as stream:
        stream.write("\nCOPY --chmod=755 fake-codex /usr/local/bin/codex\n")
    return task


def _run_job(
    task: Path, directory: Path, *, cancel: bool = False, timeout_seconds: float = 10
) -> Path:
    config = yaml.safe_load(EXAMPLE.read_text())
    config["tasks"] = [{"path": str(task)}]
    config["jobs_dir"] = str(directory / "jobs")
    config["job_name"] = "control"
    config["agents"][0]["override_timeout_sec"] = timeout_seconds
    config_path = directory / "job.yaml"
    config_path.write_text(yaml.safe_dump(config))
    job = directory / "jobs/control"
    environment = dict(os.environ)
    for key in (
        "CODEX_AUTH_JSON_PATH",
        "CODEX_FORCE_AUTH_JSON",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        environment.pop(key, None)
    with (directory / "harbor.log").open("w") as log:
        process = subprocess.Popen(
            ["harbor", "run", "-c", str(config_path)],
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            if cancel:
                deadline = time.monotonic() + 120
                while not list(job.glob("*/agent/child-started")):
                    if process.poll() is not None or time.monotonic() > deadline:
                        pytest.fail("late child did not start; inspect harbor.log")
                    time.sleep(0.1)
                process.send_signal(signal.SIGINT)
            process.wait(timeout=180)
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                process.wait(timeout=70)
    assert process.returncode in ((0, 130) if cancel else (0,)), (
        directory / "harbor.log"
    ).read_text()
    return job
