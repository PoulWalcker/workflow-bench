"""Real Sapiens host/CLI controls with an inert external Codex process."""

import asyncio
import json
from dataclasses import replace
from functools import partial
from pathlib import Path

import pytest

from workflow_bench.composer import submit_sapiens
from workflow_bench.definition import export_public, load_task
from workflow_bench.experiment import run_measurement

ROOT = Path(__file__).resolve().parents[2]


def test_sapiens_native_submission_reaches_unchanged_evaluation(
    e1_config, request, sapiens_control
):
    config_path = request.config.getoption("--sapiens-config")
    task_path = request.config.getoption("--measurement-task")
    if not config_path or not task_path:
        pytest.fail("pass --sapiens-config and --measurement-task")
    composer = sapiens_control("submit")
    result = asyncio.run(
        run_measurement(
            Path(task_path).resolve(),
            config=replace(e1_config, total_timeout_sec=1800),
            submit=partial(submit_sapiens, composer=composer),
        )
    )
    assert result["attempt_count"] == 1
    assert (result["score"], result["verdict"], result["completeness"]) == (
        10,
        "pass",
        "complete",
    )
    creation = e1_config.output_root / "attempt-1/creation"
    facts = json.loads((creation / "creation.json").read_text())
    assert facts["model_calls"] == 0 and facts["tool_calls"] == 3
    assert facts["stop_confirmed"]
    assert not facts["cleanup_errors"] and not facts["residual_resources"]
    terminal = next(creation.glob("harbor/*/agent/sapiens-terminal.json"))
    assert json.loads(terminal.read_text())["data"]["state"] == "Completed"


@pytest.fixture
def sapiens_control(e1_config, request):
    import shutil
    import subprocess
    from uuid import uuid4

    config_path = request.config.getoption("--sapiens-config")
    if not config_path:
        pytest.fail("prepare --sapiens-config")
    document = json.loads(Path(config_path).read_text())
    context = e1_config.output_root.parent / "control-image"
    context.mkdir()
    shutil.copyfile(
        Path(__file__).with_name("sapiens_codex_stub.py"), context / "codex"
    )
    task_path = request.config.getoption("--measurement-task")
    workflow = (
        Path(task_path) if task_path else ROOT / "tasks/t1-send-message"
    ) / "solution/workflow.json"
    shutil.copyfile(workflow, context / "workflow.json")
    tag = "wb08-control-" + uuid4().hex
    base_tag = tag + "-base"
    subprocess.run(
        ["docker", "tag", document["composer"]["image"], base_tag],
        check=True,
        timeout=10,
    )

    def prepare(mode):
        (context / "mode").write_text(mode)
        (context / "Dockerfile").write_text(
            f"FROM {base_tag}\n"
            "RUN mv /usr/local/bin/codex /usr/local/bin/codex-real\n"
            "COPY codex /usr/local/bin/codex\nRUN chmod 755 /usr/local/bin/codex\n"
            "COPY workflow.json /synthetic-workflow.json\nCOPY mode /synthetic-mode\n"
        )
        with (context / "build.log").open("w") as log:
            subprocess.run(
                ["docker", "build", "--network=none", "-t", tag, str(context)],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=60,
            )
        composer = dict(document["composer"])
        composer["image"] = subprocess.check_output(
            ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
            text=True,
            timeout=10,
        ).strip()
        return composer

    try:
        yield prepare
    finally:
        for name in (tag, base_tag):
            subprocess.run(
                ["docker", "image", "rm", name],
                capture_output=True,
                check=True,
                timeout=10,
            )


@pytest.mark.parametrize("mode", ["timeout", "cancel", "native-cancel", "disconnect"])
def test_sapiens_stops_host_and_late_child(e1_config, sapiens_control, mode):
    from uuid import uuid4

    from workflow_bench.evaluation import read_evidence
    from workflow_bench.harbor import assert_stopped

    composer = sapiens_control(mode)
    public = export_public(
        load_task(
            ROOT / "tasks/t1-send-message",
            tool_contract=ROOT / "simapps/telegram/tools.json",
        ),
        e1_config.output_root.parent / "public",
    )

    async def check():
        from workflow_bench.n8n_contracts import SUBMISSION_TRIAL_PREFIX

        attempt = uuid4().hex
        run_id = uuid4().hex
        pending = asyncio.create_task(
            submit_sapiens(
                public=public,
                root=e1_config.output_root,
                run_id=run_id,
                attempt_id=attempt,
                previous=None,
                feedback=[],
                config=replace(
                    e1_config, submission_timeout_sec=8 if mode == "timeout" else 30
                ),
                composer=composer,
            )
        )
        if mode != "timeout":
            async with asyncio.timeout(90):
                while not list(
                    e1_config.output_root.glob("harbor/*/agent/sapiens-child.json")
                ):
                    if pending.done():
                        pytest.fail("child control did not start")
                    await asyncio.sleep(0.2)
            if mode == "cancel":
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                from workflow_bench.harbor import docker
                from workflow_bench_integrations.sapiens import CLI

                container = await docker(
                    "ps",
                    "--filter",
                    "label=com.docker.compose.project="
                    + SUBMISSION_TRIAL_PREFIX
                    + attempt
                    + "__env",
                    "--filter",
                    "label=com.docker.compose.service=main",
                    "--format",
                    "{{.ID}}",
                )
                receipt = next(
                    e1_config.output_root.glob("harbor/*/agent/sapiens-accepted.json")
                )
                turn_id = json.loads(receipt.read_text())["data"]["id"]
                import shlex

                if mode == "native-cancel":
                    cancelled = await docker(
                        "exec",
                        container,
                        "sh",
                        "-c",
                        CLI + "conversation cancel " + shlex.quote(turn_id),
                    )
                    assert json.loads(cancelled)["ok"]
                else:
                    await docker(
                        "exec",
                        container,
                        "sh",
                        "-c",
                        'kill -KILL "$(cat /tmp/sapiens-host.pid)"',
                    )
        if mode != "cancel":
            result = await pending
            assert result.process_status == "unknown" and result.stop_confirmed
            assert result.path is None
        if mode == "native-cancel":
            terminal = next(
                e1_config.output_root.glob("harbor/*/agent/sapiens-terminal.json")
            )
            assert json.loads(terminal.read_text())["data"]["state"] in {
                "Interrupted",
                "Cancelled",
            }
        if mode == "disconnect":
            terminal = next(
                e1_config.output_root.glob("harbor/*/agent/sapiens-terminal.json")
            )
            assert (
                json.loads(terminal.read_text())["error"]["code"] == "HOST_UNAVAILABLE"
            )
        creation = json.loads((e1_config.output_root / "creation.json").read_text())
        assert creation["stop_confirmed"]
        assert not creation["cleanup_errors"] and not creation["residual_resources"]
        assert list(e1_config.output_root.glob("harbor/*/agent/sapiens-child.json"))
        session = next(
            e1_config.output_root.glob("harbor/*/agent/sessions/control.jsonl"), None
        )
        assert session is not None, "native sessions must survive host/child cleanup"
        assert json.loads(session.read_text())["payload"]["phase"] == "execution"
        assert not list(e1_config.output_root.glob("harbor/*/agent/**/auth.json"))
        evidence = e1_config.output_root / "exploration.json"
        identity = json.loads(evidence.read_text())["identity"]
        facts = read_evidence(
            evidence,
            expected_identity={**identity, "run_id": run_id, "attempt_id": attempt},
        ).document
        assert facts["freeze_status"] == "complete" and not facts["pending_call_ids"]
        assert facts["after"]["revision"] > facts["before"]["revision"]
        assert not list(
            e1_config.output_root.glob("harbor/*/artifacts/work/workflow.json")
        )
        await assert_stopped(SUBMISSION_TRIAL_PREFIX + attempt + "__env", deleted=True)

    asyncio.run(check())


def test_sapiens_stock_codex_failure_is_terminal_not_submission(e1_config, request):
    from uuid import uuid4

    config_path = request.config.getoption("--sapiens-config")
    if not config_path:
        pytest.fail("prepare --sapiens-config")
    composer = json.loads(Path(config_path).read_text())["composer"]
    public = export_public(
        load_task(
            ROOT / "tasks/t1-send-message",
            tool_contract=ROOT / "simapps/telegram/tools.json",
        ),
        e1_config.output_root.parent / "public",
    )
    result = asyncio.run(
        submit_sapiens(
            public=public,
            root=e1_config.output_root,
            run_id=uuid4().hex,
            attempt_id=uuid4().hex,
            previous=None,
            feedback=[],
            config=e1_config,
            composer=composer,
        )
    )
    assert result.path is None and result.stop_confirmed
    assert result.process_status == "unknown" and result.metrics["model_calls"] == 0
    assert (
        not result.metrics["cleanup_errors"]
        and not result.metrics["residual_resources"]
    )
    terminal = next(e1_config.output_root.glob("harbor/*/agent/sapiens-terminal.json"))
    data = json.loads(terminal.read_text())
    assert not data["ok"] and data["data"]["state"].casefold() == "failed"
    sessions = list(e1_config.output_root.glob("harbor/*/agent/sessions/**/*.jsonl"))
    assert sessions, "real internal Codex must retain its native sessions"
    assert any(
        json.loads(line).get("type") == "session_meta"
        for session in sessions
        for line in session.read_text().splitlines()
    )
    assert not list(e1_config.output_root.glob("harbor/*/agent/**/auth.json"))
