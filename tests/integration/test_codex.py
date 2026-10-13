"""Native Codex-adapter wiring with an inert CLI and synthetic credentials."""

import asyncio
import hashlib
import json
import shutil
import subprocess
import threading
from dataclasses import replace
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import pytest

from workflow_bench.composer import submit_codex
from workflow_bench.definition import export_public, load_task
from workflow_bench.execution import accept_artifact, replay
from workflow_bench.experiment import run_measurement
from workflow_bench.harbor import replay_environment
from workflow_bench.n8n_contracts import SUBMISSION_TRIAL_PREFIX

ROOT = Path(__file__).resolve().parents[2]


def test_packaged_mcp_discovery_without_ambient_pythonpath(e1_config):
    """Codex filters PYTHONPATH from stdio servers, unlike the inert CLI."""
    name = "wb07-mcp-discovery-" + uuid4().hex
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        },
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--network",
                "none",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "-i",
                "--env",
                "WB_TOOL_URL=http://127.0.0.1:9",
                "--env",
                "WB_CAPABILITY=synthetic",
                e1_config.app_image,
                "env",
                "-u",
                "PYTHONPATH",
                "python",
                "-m",
                "workflow_bench.mcp",
                "--contract",
                "/app/simapp/tools.json",
                "--timeout",
                "1",
            ],
            input="".join(json.dumps(request) + "\n" for request in requests),
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr
        initialized, listed = [json.loads(line) for line in result.stdout.splitlines()]
        assert initialized["result"]["serverInfo"]["name"] == "workflow-bench-tools"
        assert {tool["name"] for tool in listed["result"]["tools"]} == {
            "get_chat",
            "list_messages",
            "send_message",
        }
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True,
            timeout=10,
        )


@pytest.fixture
def private_host_port():
    class PrivateHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"synthetic-private-host-marker")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("0.0.0.0", 0), PrivateHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def control_image(config, root, mode, private_host_port, workflow):
    context = root / "control-image"
    context.mkdir()
    shutil.copyfile(Path(__file__).with_name("codex_stub.py"), context / "codex")
    shutil.copyfile(workflow, context / "workflow.json")
    (context / "mode").write_text(mode)
    (context / "host-port").write_text(str(private_host_port))
    tag = "wb07-control-" + uuid4().hex
    base_tag = tag + "-base"
    subprocess.run(
        ["docker", "tag", config.app_image, base_tag], check=True, timeout=10
    )
    (context / "Dockerfile").write_text(
        f"FROM {base_tag}\nCOPY codex /usr/local/bin/codex\nRUN chmod 755 /usr/local/bin/codex\nCOPY workflow.json /synthetic-workflow.json\nCOPY mode /synthetic-mode\nCOPY host-port /synthetic-host-port\n"
    )
    try:
        with (root / "control-image.log").open("w") as log:
            subprocess.run(
                ["docker", "build", "--network=none", "-t", tag, str(context)],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=60,
            )
    finally:
        subprocess.run(
            ["docker", "image", "rm", base_tag],
            check=True,
            capture_output=True,
            timeout=10,
        )
    image = subprocess.check_output(
        ["docker", "image", "inspect", tag, "--format", "{{.Id}}"],
        text=True,
        timeout=10,
    ).strip()
    return {
        "mode": "model-free",
        "image": image,
        "cli_version": "0.118.0",
        "model": "synthetic",
        "reasoning_effort": "low",
        "exploration_max_calls": 4,
    }, tag


def test_inert_codex_submission_uses_existing_five_plus_five(
    e1_config, request, private_host_port
):
    task_path = request.config.getoption("--measurement-task")
    if not task_path:
        pytest.fail("pass a frozen private Task with --measurement-task")
    root = e1_config.output_root.parent
    composer, tag = control_image(
        e1_config,
        root,
        "submit",
        private_host_port,
        Path(task_path) / "solution/workflow.json",
    )
    try:
        result = asyncio.run(
            run_measurement(
                Path(task_path).resolve(),
                config=replace(e1_config, total_timeout_sec=1800),
                submit=partial(submit_codex, composer=composer),
            )
        )
        assert result["attempt_count"] == 1 and result["score"] == 10
        assert result["verdict"] == "pass" and result["completeness"] == "complete"
        assert result["model_calls"] == 0
        assert result["efficiency"]["creation"]["input_tokens"] is None
        creation = json.loads(
            (e1_config.output_root / "attempt-1/creation/creation.json").read_bytes()
        )
        assert (
            creation["stop_confirmed"]
            and not creation["cleanup_errors"]
            and not creation["residual_resources"]
        )
        json.loads(
            (
                e1_config.output_root
                / "attempt-1/creation"
                / creation["harbor_result_ref"]
            ).read_bytes()
        )
        assert creation["tool_calls"] == 3
        isolation = json.loads(
            (e1_config.output_root / "attempt-1/creation/isolation.json").read_bytes()
        )
        assert isolation["control_url"].endswith(
            f":{e1_config.control_port}/control/export"
        )
        assert isolation["reachability"] == {"main": False, "provider": False}
        facts = json.loads(
            (e1_config.output_root / "attempt-1/creation/exploration.json").read_bytes()
        )
        assert facts["freeze_status"] == "complete"
        assert facts["after"]["state"] != facts["before"]["state"]
        assert (
            e1_config.output_root / "attempt-1/creation/native-task/instruction.md"
        ).read_bytes() == (Path(task_path) / "instruction.md").read_bytes()
        assert (
            result["selection"]["artifact_hash"]
            == hashlib.sha256(
                (Path(task_path) / "solution/workflow.json").read_bytes()
            ).hexdigest()
        )
        assert not (
            e1_config.output_root / "attempt-1/creation/connection.json"
        ).exists()
    finally:
        subprocess.run(
            ["docker", "image", "rm", tag], check=True, capture_output=True, timeout=10
        )


@pytest.mark.parametrize("mode", ["timeout", "cancel"])
def test_native_codex_stops_child_writer_and_revokes_tools(
    e1_config, mode, private_host_port
):
    root = e1_config.output_root.parent
    composer, tag = control_image(
        e1_config,
        root,
        mode,
        private_host_port,
        ROOT / "tasks/t1-send-message/solution/workflow.json",
    )
    public = export_public(
        load_task(
            ROOT / "tasks/t1-send-message",
            tool_contract=ROOT / "simapps/telegram/tools.json",
        ),
        root / "public",
    )

    async def run():
        attempt = uuid4().hex
        config = replace(e1_config, submission_timeout_sec=8)
        pending = asyncio.create_task(
            submit_codex(
                public=public,
                root=e1_config.output_root,
                run_id=uuid4().hex,
                attempt_id=attempt,
                previous=None,
                feedback=[],
                config=config,
                composer=composer,
            )
        )
        if mode == "cancel":
            logs = (
                e1_config.output_root
                / "harbor"
                / (SUBMISSION_TRIAL_PREFIX + attempt)
                / "agent/codex.txt"
            )
            async with asyncio.timeout(90):
                while not logs.exists() or "child-started" not in logs.read_text():
                    await asyncio.sleep(0.2)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            result = await pending
            assert result.process_status == "unknown" and result.stop_confirmed
            assert result.path is None
        record = json.loads((e1_config.output_root / "creation.json").read_bytes())
        assert record["stop_confirmed"]
        assert not record["cleanup_errors"] and not record["residual_resources"]
        facts = json.loads((e1_config.output_root / "exploration.json").read_bytes())
        assert facts["freeze_status"] == "complete" and not facts["pending_call_ids"]
        assert len(facts["after"]["state"]["messages"]) == 1
        assert not list(
            e1_config.output_root.glob("harbor/*/artifacts/work/workflow.json")
        )

    try:
        asyncio.run(run())
    finally:
        subprocess.run(
            ["docker", "image", "rm", tag], check=True, capture_output=True, timeout=10
        )


@pytest.mark.parametrize("mode", ["submit", "session-fifo"])
def test_inventory_composer_and_replay_use_only_the_public_app_contract(
    e1_config, private_host_port, mode
):
    fixture = Path(__file__).parent / "fixtures/inventory"
    root = e1_config.output_root.parent
    public = export_public(
        load_task(fixture / "task", tool_contract=fixture / "simapp/tools.json"),
        root / "public",
    )
    config = replace(e1_config, control_port=8189)
    composer, tag = control_image(
        config,
        root,
        mode,
        private_host_port,
        fixture / "task/solution/workflow.json",
    )

    async def check():
        creation = root / "creation"
        result = await submit_codex(
            public=public,
            root=creation,
            run_id=uuid4().hex,
            attempt_id=uuid4().hex,
            previous=None,
            feedback=[],
            config=config,
            composer=composer,
        )
        assert result.stop_confirmed and result.process_status == "completed"
        if mode == "session-fifo":
            assert result.metrics["raw_usage"]["input_tokens"] is None
            assert result.metrics["raw_usage"]["raw_refs"]
        assert (creation / "native-task/instruction.md").read_bytes() == (
            fixture / "task/instruction.md"
        ).read_bytes()
        isolation = json.loads((creation / "isolation.json").read_bytes())
        assert isolation["control_url"].endswith(":8189/control/export")
        assert isolation["reachability"] == {"main": False, "provider": False}
        exploration = json.loads((creation / "exploration.json").read_bytes())
        assert exploration["after"]["state"] == {"stock": [], "reservations": ["book"]}
        artifact = accept_artifact(
            result.path, submission_stopped=True, destination=root / "accepted.json"
        )
        identity = {
            **exploration["identity"],
            "replay_id": uuid4().hex,
            "case_id": "new-input",
            "artifact_hash": artifact.sha256,
        }
        config.output_root.mkdir()
        async with replay_environment(config, identity) as context:
            await context.control(
                "reset",
                {
                    "identity": identity,
                    "state": {"stock": ["pen", "other"], "reservations": []},
                    "profile": identity["profile"],
                    "limits": {"call_timeout_sec": config.tool_timeout_sec},
                },
            )
            await context.check_isolation()
            execution, _ = await replay(
                artifact, {"item": "pen"}, context=context, config=config
            )
            assert (
                execution["process_status"] == "completed"
                and execution["claim"]["status"] == "completed"
            )
            from workflow_bench.evaluation import read_evidence

            evidence_path = context.root / "evidence.json"
            evidence_path.write_text(json.dumps(await context.control("export")))
            facts = read_evidence(evidence_path, expected_identity=identity).document
            assert facts["after"]["state"] == {
                "stock": ["other"],
                "reservations": ["pen"],
            }
            assert facts["freeze_status"] == "complete"

    try:
        asyncio.run(check())
    finally:
        subprocess.run(
            ["docker", "image", "rm", tag], check=True, capture_output=True, timeout=10
        )
