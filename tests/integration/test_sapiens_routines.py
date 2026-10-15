"""Model-free routine lifetime and post-phase state through a native Harbor Trial."""

import json
import subprocess
from pathlib import Path

from tests.integration.test_sapiens_controls import (
    _assert_observation,
    _fake_task,
    _run_job,
    _summary,
)


def test_routine_fires_after_setup_and_refreshes_saved_state(
    trivial_task: Path, tmp_path: Path
) -> None:
    task = _fake_task(trivial_task, tmp_path, "routine")
    with (task / "task.toml").open("a") as stream:
        stream.write(
            '\n[[verifier.collect]]\nservice = "main"\n'
            'command = "sleep 150"\ntimeout_sec = 170\n'
        )
    job = _run_job(task, tmp_path)
    assert _summary(job)["outcome"] == "pass"
    _assert_observation(job, "completed")
    trial = next(job.glob("*/result.json")).parent
    state = json.loads((trial / "agent/sapiens-state.json").read_text())
    assert state["routines"][0]["minutes"] == 1
    assert state["routines"][0]["runCount"] >= 2
    assert (
        len(
            [
                work
                for work in state["workloads"]
                if work.get("origin", {}).get("routine")
            ]
        )
        >= 2
    )
    firings = [
        json.loads(line)
        for line in (trial / "agent/routine-firings.jsonl").read_text().splitlines()
    ]
    assert len(firings) >= 2
    native = json.loads((trial / "result.json").read_text())
    assert all(
        firing["at"] > native["agent_execution"]["finished_at"] for firing in firings
    )
    assert (trial / "agent/sapiens-state-refresh.pid").read_text().strip().isdigit()
    assert "cleanup result=confirmed" in (trial / "trial.log").read_text()
    containers = subprocess.run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"label=com.docker.compose.project={trial.name.lower()}__env",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert containers.stdout == ""
