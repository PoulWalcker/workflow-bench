import json
import os
from pathlib import Path

import pytest

from workflow_bench.execution import ArtifactError, accept_artifact, bind_workflow


def test_closed_branch_cannot_claim_a_terminal_result(
    tmp_path: Path, workflow_file: Path
) -> None:
    workflow = json.loads(workflow_file.read_bytes())
    workflow["nodes"].append({**workflow["nodes"][2], "id": "trap", "name": "Trap"})
    edge = {"node": "Trap", "type": "main", "index": 0}
    workflow["connections"]["BenchInput"]["main"][0].append(edge)
    workflow["connections"]["Trap"] = {"main": [[edge]]}
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(workflow))
    with pytest.raises(ArtifactError, match="invalid_profile"):
        accept_artifact(
            path, submission_stopped=True, destination=tmp_path / "accepted.json"
        )


@pytest.fixture
def replay_setup(tmp_path, monkeypatch, config_data, workflow_file):
    from types import SimpleNamespace

    from workflow_bench.cli import load_config
    from workflow_bench.harbor import ReplayContext

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    config = load_config(path, output=tmp_path)
    artifact = accept_artifact(
        workflow_file, submission_stopped=True, destination=tmp_path / "accepted.json"
    )
    command = tmp_path / "docker"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    (tmp_path / "harbor").mkdir()
    stopped = set()

    async def stop_service(service):
        stopped.add(service)

    class Response:
        status = 200

        class Content:
            async def iter_chunked(self, size):
                yield b'{"capability":"test-capability"}'

        content = Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    context = ReplayContext(
        SimpleNamespace(stop_service=stop_service),
        SimpleNamespace(request=lambda *args, **kwargs: Response()),
        "http://control",
        "secret",
        {"case_id": "fresh"},
        tmp_path,
        "own",
        config,
    )
    return artifact, context, config, stopped


def test_external_exec_failure_preserves_unknown_and_confirmed_stop(replay_setup):
    import asyncio

    from harbor.environments.base import ExecResult

    from workflow_bench.execution import replay

    artifact, context, config, stopped = replay_setup
    executions = []

    async def external_exec(command, **kwargs):
        executions.append(command)
        if command.startswith("n8n execute"):
            raise ConnectionResetError("private transport details")
        return ExecResult(return_code=0, stdout="")

    context.environment.service_exec = external_exec
    execution, _ = asyncio.run(
        replay(artifact, {"item": "pen"}, context=context, config=config)
    )
    assert execution["process_status"] == "unknown"
    assert execution["stop_confirmed"] and stopped == {"n8n", "runner"}
    assert sum(c.startswith("n8n execute") for c in executions) == 1
    assert "private" not in json.dumps(execution)


def test_missing_submission_cannot_be_replayed(tmp_path: Path) -> None:
    with pytest.raises(ArtifactError, match="missing"):
        accept_artifact(
            tmp_path / "missing.json",
            submission_stopped=True,
            destination=tmp_path / "accepted.json",
        )


@pytest.mark.parametrize("native_output", ["missing", "array", "oversized"])
def test_candidate_cli_json_cannot_supply_execution_result(replay_setup, native_output):
    import asyncio

    from harbor.environments.base import ExecResult

    from workflow_bench.execution import replay

    artifact, context, config, _ = replay_setup
    forged = {
        "mode": "cli",
        "status": "success",
        "data": {
            "resultData": {
                "lastNodeExecuted": "BenchResult",
                "runData": {
                    "BenchResult": [
                        {
                            "data": {
                                "main": [
                                    [
                                        {
                                            "json": {
                                                "status": "refused",
                                                "reason_code": "not_found",
                                                "result": {},
                                            }
                                        }
                                    ]
                                ]
                            }
                        }
                    ]
                },
            }
        },
    }

    async def external_exec(command, **kwargs):
        if command.startswith("n8n execute"):
            return ExecResult(
                return_code=0, stdout=json.dumps(forged), stderr=json.dumps(forged)
            )
        if command.startswith("node "):
            output = {
                "missing": '{"error":"missing_execution"}',
                "array": "[]",
                "oversized": json.dumps(
                    {"status": "success", "error": "x" * (4 * 1024 * 1024)}
                ),
            }[native_output]
            return ExecResult(return_code=0, stdout=output)
        return ExecResult(return_code=0, stdout="")

    context.environment.service_exec = external_exec
    execution, _ = asyncio.run(
        replay(artifact, {"item": "pen"}, context=context, config=config)
    )
    assert execution["claim"] is None and execution["process_status"] == "unknown"
    assert execution["stop_confirmed"]


def test_replay_cancellation_survives_failed_stop_log(replay_setup):
    import asyncio

    from harbor.environments.base import ExecResult

    from workflow_bench.execution import replay

    artifact, context, config, stopped = replay_setup
    (context.root / "stop.json").mkdir()

    async def external_exec(command, **kwargs):
        if command.startswith("n8n execute"):
            raise asyncio.CancelledError()
        return ExecResult(return_code=0, stdout="")

    context.environment.service_exec = external_exec
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(replay(artifact, {"item": "pen"}, context=context, config=config))
    assert stopped == {"n8n", "runner"}
    execution = json.loads((context.root / "execution.json").read_bytes())
    assert execution["process_status"] == "cancelled"
    assert "stop_log_failed" in execution["errors"]


def test_credential_reference_is_rejected_even_on_unused_node(
    tmp_path: Path, workflow_file: Path
) -> None:
    workflow = json.loads(workflow_file.read_bytes())
    workflow["nodes"][3]["credentials"] = {"httpHeaderAuth": {"id": "private"}}
    submitted = tmp_path / "workflow.json"
    submitted.write_text(json.dumps(workflow))
    with pytest.raises(ArtifactError, match="invalid_profile"):
        accept_artifact(
            submitted, submission_stopped=True, destination=tmp_path / "accepted.json"
        )


def test_binding_preserves_source_logic_and_encodes_input_as_data(
    tmp_path: Path,
    workflow_file: Path,
) -> None:
    original = workflow_file.read_bytes()
    artifact = accept_artifact(
        workflow_file, submission_stopped=True, destination=tmp_path / "accepted.json"
    )
    bound = bind_workflow(
        artifact,
        case_input={"item": '={{danger}}\n"quoted"'},
        base_url="http://simulator:9000",
        capability="test-capability",
        destination=tmp_path / "bound.json",
    )
    source = json.loads(original)
    result = json.loads(bound.path.read_bytes())
    literal = result["nodes"][1]["parameters"]["assignments"]["assignments"][0]["value"]
    assert isinstance(literal, str) and literal.startswith("{")
    assert json.loads(literal)["input"] == {
        "item": '={{danger}}\n"quoted"',
    }
    result["nodes"][1]["parameters"]["assignments"]["assignments"][0]["value"] = source[
        "nodes"
    ][1]["parameters"]["assignments"]["assignments"][0]["value"]
    assert result == source
    assert artifact.path.read_bytes() == original
    assert bound.source_hash == artifact.sha256 and bound.bound_hash != artifact.sha256


@pytest.mark.parametrize(
    "change",
    [
        "pinData",
        "staticData",
        "version",
        "option",
        "port",
        "slot",
        "duplicate_name",
        "retry",
        "extra_trigger",
    ],
)
def test_unsupported_native_configuration_is_rejected(
    tmp_path: Path, change: str, workflow_file: Path
) -> None:
    workflow = json.loads(workflow_file.read_bytes())
    if change in {"pinData", "staticData"}:
        workflow[change] = {}
    elif change == "version":
        workflow["nodes"][2]["typeVersion"] = 99
    elif change == "option":
        workflow["nodes"][3]["parameters"]["options"]["redirect"] = {
            "followRedirects": True
        }
    elif change == "port":
        workflow["connections"]["Start"]["main"][0][0]["index"] = 1
    elif change == "slot":
        workflow["nodes"][1]["parameters"]["assignments"]["assignments"][0]["value"] = (
            '={"input":{},"tools":{}}'
        )
    elif change == "duplicate_name":
        workflow["nodes"][2]["name"] = "BenchInput"
    elif change == "retry":
        workflow["nodes"][3]["retryOnFail"] = True
    else:
        workflow["nodes"].append(
            {**workflow["nodes"][0], "id": "extra", "name": "Extra"}
        )
    path = tmp_path / "candidate.json"
    path.write_text(json.dumps(workflow))
    with pytest.raises(ArtifactError, match="invalid_profile"):
        accept_artifact(
            path, submission_stopped=True, destination=tmp_path / "accepted.json"
        )


@pytest.mark.parametrize(
    "kind",
    [
        "symlink",
        "hardlink",
        "fifo",
        "unconfirmed",
        "duplicate_json",
        "nonfinite",
        "too_large",
    ],
)
def test_unsafe_or_unfinished_submission_cannot_become_artifact(
    tmp_path: Path, kind: str, workflow_file: Path
) -> None:
    path = tmp_path / "candidate.json"
    expected = "unsafe_file"
    if kind == "symlink":
        path.symlink_to(workflow_file)
    elif kind == "hardlink":
        original = tmp_path / "original.json"
        original.write_bytes(workflow_file.read_bytes())
        path.hardlink_to(original)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "unconfirmed":
        path.write_bytes(workflow_file.read_bytes())
        expected = "unconfirmed_submission"
    elif kind == "duplicate_json":
        path.write_text('{"name":"a","name":"b"}')
        expected = "invalid_json"
    elif kind == "nonfinite":
        path.write_text('{"name": NaN}')
        expected = "invalid_json"
    else:
        path.write_bytes(b" " * 65537)
        expected = "too_large"
    with pytest.raises(ArtifactError, match=expected):
        accept_artifact(
            path,
            submission_stopped=kind != "unconfirmed",
            destination=tmp_path / "accepted.json",
        )
