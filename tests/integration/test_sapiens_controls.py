"""Model-free Sapiens controls through native Harbor Trials."""

import json
import os
import shutil
import signal
import subprocess
import time
from contextlib import suppress
from pathlib import Path

import pytest
import yaml

from workflow_bench.comparison import TrialSummary, compare, summarize
from workflow_bench.transcript import render_trial_transcript

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/sapiens/job.yaml"
FAKE_CODEX = Path(__file__).parent / "assets/fake_sapiens_codex.py"


def test_chief_completes_trivial_task_without_delegation(
    trivial_task: Path, tmp_path: Path
) -> None:
    job = _run_job(_fake_task(trivial_task, tmp_path, "direct"), tmp_path)
    assert _summary(job)["outcome"] == "pass"
    native = json.loads(next(job.glob("*/result.json")).read_text())
    assert native["agent_result"]["metadata"]["sapiens_outcome"] == "completed"
    _assert_observation(job, "completed")
    trial_dir = next(job.glob("*/result.json")).parent
    lines = (trial_dir / "trial.log").read_text().splitlines()
    assert any(
        "phase=verifier result=pass criteria=3 failed=none" in line for line in lines
    )
    assert any(
        "phase=sapiens-cli" in line and "subcommand=doctor" in line for line in lines
    )
    assert any(
        "phase=sapiens-cli" in line and "subcommand=chat" in line for line in lines
    )
    assert any(
        "phase=sapiens-transition" in line and "kind=turn" in line for line in lines
    )
    assert any(
        "phase=sapiens-transition" in line and "kind=workload" in line for line in lines
    )
    assert (trial_dir / "agent/sapiens-host.txt").is_file()


def test_chief_waits_for_new_specialist_to_complete(
    trivial_task: Path, tmp_path: Path
) -> None:
    job = _run_job(_fake_task(trivial_task, tmp_path, "delegate"), tmp_path)
    assert _summary(job)["outcome"] == "pass"
    marker = json.loads(next(job.glob("*/agent/specialist-executed.json")).read_text())
    assert marker["self"] != marker["chief"]
    trial_dir = next(job.glob("*/result.json")).parent
    state = json.loads((trial_dir / "agent/sapiens-state.json").read_text())
    assert any(agent["id"] == marker["self"] for agent in state["agents"])
    transcript = render_trial_transcript(trial_dir, _summary(job))
    assert "Chief —" in transcript
    assert "BasketExpert —" in transcript
    assert "Delegation to BasketExpert" in transcript
    assert "[missing: Sapiens state" not in transcript
    _assert_observation(job, "completed")


def test_unclear_request_is_judged_from_world_state(
    trivial_task: Path, tmp_path: Path
) -> None:
    job = _run_job(_fake_task(trivial_task, tmp_path, "unclear"), tmp_path)
    summary = _summary(job)
    assert summary["outcome"] == "fail"
    assert summary["evaluation"] is not None
    assert summary["evaluation"]["verdict"] == "fail"
    native = json.loads(next(job.glob("*/result.json")).read_text())
    assert native["agent_result"]["metadata"]["sapiens_outcome"] == "agent_outcome"
    decision = json.loads(next(job.glob("*/agent/unclear-decision.json")).read_text())
    assert decision["event"] == "RequestUnclear"
    terminal = json.loads(next(job.glob("*/agent/sapiens-terminal.json")).read_text())
    assert "WaitingForAdmin" in terminal["workload_states"]
    _assert_observation(job, "agent_outcome", workload_state="WaitingForAdmin")


@pytest.mark.parametrize("is_cancelled", [False, True], ids=["timeout", "cancel"])
def test_stop_kills_late_child_and_sapiens_host(
    trivial_task: Path, tmp_path: Path, is_cancelled: bool
) -> None:
    job = _run_job(
        _fake_task(trivial_task, tmp_path, "stop"),
        tmp_path,
        is_cancelled=is_cancelled,
        timeout_seconds=60 if is_cancelled else 3,
    )
    assert list(job.glob("*/agent/child-started"))
    observation = next(job.glob("*/trial.log")).read_text()
    assert "phase=sapiens-observation" in observation
    assert "result=started" in observation
    time.sleep(9)
    assert not list(job.glob("*/agent/late-write"))
    trial = next(job.glob("*/result.json")).parent.name
    running = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={trial.lower()}__env",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert running.stdout == ""


def test_real_codex_accepts_sapiens_exec_arguments_without_a_provider(
    trivial_task: Path, tmp_path: Path
) -> None:
    task = _empty_provider_task(trivial_task, tmp_path)
    job = _run_job(task, tmp_path, provider_url="http://127.0.0.1:8765/v1")
    summary = _summary(job)
    assert summary["outcome"] == "fail"
    assert summary["evaluation"] is not None
    assert summary["evaluation"]["verdict"] == "fail"
    native = json.loads(next(job.glob("*/result.json")).read_text())
    assert native["agent_result"]["metadata"]["sapiens_outcome"] == "agent_outcome"
    session = next(job.glob("*/agent/sessions/**/*.jsonl"))
    events = [json.loads(line) for line in session.read_text().splitlines()]
    metadata = events[0]["payload"]
    assert metadata["cli_version"] == "0.162.1"
    assert metadata["model_provider"] == "empty"
    completed = next(
        event["payload"]
        for event in events
        if event["type"] == "event_msg"
        and event["payload"].get("type") == "task_complete"
    )
    assert "401 Unauthorized: empty test provider" in completed["error"]["message"]
    _assert_observation(job, "agent_outcome")


def _assert_observation(
    job: Path, expected_decision: str, *, workload_state: str | None = None
) -> None:
    """Check the Trial log's bounded observation record for a completed control."""
    trial_log = next(job.glob("*/trial.log"))
    lines = [
        line
        for line in trial_log.read_text().splitlines()
        if "phase=sapiens-observation" in line
    ]
    assert len(lines) == 2
    assert all("at=" in line for line in lines)
    assert all(f"trial={trial_log.parent.name}" in line for line in lines)
    assert all("sapiens_turn_id=" in line for line in lines)
    assert "result=started" in lines[0]
    assert f"result={expected_decision}" in lines[1]
    assert "turn_states=" in lines[1]
    assert "workload_states=" in lines[1]
    assert "run_activity_empty=true quiet_ticks=2" in lines[1]
    if workload_state is not None:
        states = lines[1].split("workload_states=", 1)[1].split()[0].split(",")
        assert workload_state in states


def _fake_task(source: Path, directory: Path, scenario: str) -> Path:
    task = directory / "task"
    shutil.copytree(source, task, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(FAKE_CODEX, task / "environment/fake-codex")
    with (task / "environment/Dockerfile").open("a") as stream:
        stream.write("\nCOPY --chmod=755 fake-codex /usr/local/bin/codex\n")
        stream.write(f"ENV WB_SAPIENS_SCENARIO={scenario}\n")
    return task


def _empty_provider_task(source: Path, directory: Path) -> Path:
    task = directory / "task"
    shutil.copytree(source, task, ignore=shutil.ignore_patterns("__pycache__"))
    assets = Path(__file__).parent / "assets"
    shutil.copy2(assets / "empty_provider.py", task / "environment/empty_provider.py")
    shutil.copy2(
        assets / "empty-provider-entrypoint",
        task / "environment/empty-provider-entrypoint",
    )
    with (task / "environment/Dockerfile").open("a") as stream:
        stream.write("\nCOPY empty_provider.py /usr/local/bin/empty_provider.py\n")
        stream.write(
            "COPY --chmod=755 empty-provider-entrypoint "
            "/usr/local/bin/empty-provider-entrypoint\n"
        )
        stream.write('ENTRYPOINT ["/usr/local/bin/empty-provider-entrypoint"]\n')
    return task


def _summary(job: Path) -> TrialSummary:
    report = compare([job])
    summary = summarize([job], report)
    assert len(summary["trials"]) == 1
    return summary["trials"][0]


def _run_job(
    task: Path,
    directory: Path,
    *,
    is_cancelled: bool = False,
    timeout_seconds: float = 60,
    provider_url: str | None = None,
) -> Path:
    """Run a bounded Trial, cancelling after the late child starts if asked."""
    config = yaml.safe_load(EXAMPLE.read_text())
    config["tasks"] = [{"path": str(task)}]
    config["jobs_dir"] = str(directory / "jobs")
    config["job_name"] = "control"
    config["agents"][0]["override_timeout_sec"] = timeout_seconds
    if provider_url is not None:
        config["agents"][0]["kwargs"]["config"]["model_providers"]["empty"][
            "base_url"
        ] = provider_url
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
            if is_cancelled:
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
                try:
                    process.wait(timeout=70)
                except subprocess.TimeoutExpired:
                    log.write(
                        "phase=control_cleanup result=unconfirmed "
                        f"reason=harbor_sigint_timeout harbor_pid={process.pid}\n"
                    )
                    log.flush()
                    with suppress(ProcessLookupError):
                        process.kill()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        log.write(
                            "phase=control_cleanup result=unconfirmed "
                            f"reason=harbor_kill_timeout harbor_pid={process.pid}\n"
                        )
                        log.flush()
                        raise
    assert process.returncode in ((0, 130) if is_cancelled else (0,)), (
        directory / "harbor.log"
    ).read_text()
    return job
