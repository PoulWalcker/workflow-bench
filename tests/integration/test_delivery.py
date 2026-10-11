import asyncio
import shlex
import shutil
from pathlib import Path
from uuid import uuid4

from workflow_bench.execution import accept_artifact
from workflow_bench.harbor import run_native_trial

TASK = Path(__file__).resolve().parents[2] / "tasks/t1-send-message"


def test_candidate_artifact_parent_cannot_redirect_host_collection(e1_config):
    async def check():
        e1_config.output_root.mkdir()
        stage = e1_config.output_root / "task"
        shutil.copytree(TASK, stage)
        canary_dir = e1_config.output_root / "canary"
        canary_dir.mkdir()
        canary = canary_dir / "workflow.json"
        canary.write_text("synthetic-host-private-marker")
        solve = stage / "solution/solve.sh"
        solve.write_text(
            solve.read_text()
            + "\nln -s "
            + shlex.quote(str(canary_dir))
            + " /logs/artifacts/work\n"
        )
        (stage / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")

        async def prepare(path):
            accept_artifact(
                path,
                submission_stopped=True,
                destination=e1_config.output_root / "accepted.json",
            )

        await run_native_trial(stage, uuid4().hex, prepare, config=e1_config)
        assert canary.read_text() == "synthetic-host-private-marker"
        assert (e1_config.output_root / "accepted.json").is_file()

    asyncio.run(check())
