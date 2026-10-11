import asyncio
import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from harbor.trial.trial import Trial

from workflow_bench.cli import load_config
from workflow_bench.definition import load_cases, load_task
from workflow_bench.execution import accept_artifact
from workflow_bench.experiment import run_manual


class PreparationObserved(Exception):
    pass


@pytest.mark.parametrize("linked", ["workflow", "solution"])
def test_staged_submission_rejects_links_without_modifying_source_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict,
    linked: str,
    native_task_files,
) -> None:
    from workflow_bench.data import DataError

    task, tools = native_task_files
    solution = task / "solution"
    if linked == "workflow":
        workflow = solution / "workflow.json"
        target = solution / "original.json"
        workflow.rename(target)
        workflow.symlink_to(target)
    else:
        target = task / "original-solution"
        solution.rename(target)
        solution.symlink_to(target, target_is_directory=True)
    before = {
        p.relative_to(task): p.read_bytes() for p in task.rglob("*") if p.is_file()
    }
    candidate = tmp_path / "candidate.json"
    document = json.loads((solution / "workflow.json").read_bytes())
    document["name"] = "replacement submission"
    candidate.write_text(json.dumps(document))
    submission = accept_artifact(
        candidate, submission_stopped=True, destination=tmp_path / "accepted.json"
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path / "run")

    async def exported_tools(config, **kwargs):
        return tools

    async def observe_preparation(native_config):
        raise PreparationObserved()

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    monkeypatch.setattr(Trial, "create", observe_preparation)
    try:
        with pytest.raises(DataError) as error:
            asyncio.run(
                run_manual(task, ("fresh",), config=config, submission=submission)
            )
        assert error.value.code == "unsafe_path"
        assert not (config.output_root / "manifest.json").exists()
    finally:
        assert {
            p.relative_to(task): p.read_bytes() for p in task.rglob("*") if p.is_file()
        } == before


def test_explicit_cancel_preserves_a_report_without_starting_a_trial(
    tmp_path: Path, config_data: dict, native_task_files
) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    config = load_config(path, output=tmp_path / "cancelled")

    async def check():
        cancel = asyncio.Event()
        cancel.set()
        result = await run_manual(
            native_task_files[0], ("fresh",), config=config, cancel=cancel
        )
        assert result["error"] == "cancelled" and result["score"] is None
        assert result["completeness"] == "unavailable"
        assert not (config.output_root / "harbor").exists()

    asyncio.run(check())


def test_manifest_identifies_consumed_private_snapshots_after_source_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict,
    native_task_files,
) -> None:
    task, tools = native_task_files
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path / "run-0")

    async def exported_tools(config, **kwargs):
        return tools

    async def observe_preparation(native_config):
        raise PreparationObserved()

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    monkeypatch.setattr(Trial, "create", observe_preparation)
    manifests = []
    for revision in range(2):
        rubric_path = task / "tests/rubric.json"
        rubric = json.loads(rubric_path.read_bytes())
        rubric["criteria"][0]["required"] = revision == 0
        rubric_path.write_text(json.dumps(rubric))
        cases_path = task / "tests/cases.json"
        cases = json.loads(cases_path.read_bytes())
        cases["cases"][0]["input"]["item"] = f"revision-{revision}"
        cases_path.write_text(json.dumps(cases))
        config = replace(config, output_root=tmp_path / f"run-{revision}")
        with pytest.raises(PreparationObserved):
            asyncio.run(run_manual(task, ("fresh",), config=config))
        manifest = json.loads((config.output_root / "manifest.json").read_bytes())
        for role in ("rubric_snapshot", "case_snapshot"):
            snapshot = manifest[role]
            reference = Path(snapshot["ref"])
            assert not reference.is_absolute() and ".." not in reference.parts
            content = (config.output_root / reference).read_bytes()
            assert snapshot["sha256"] == hashlib.sha256(content).hexdigest()
        applied_rubric = json.loads(
            (config.output_root / manifest["rubric_snapshot"]["ref"]).read_bytes()
        )
        assert applied_rubric == rubric
        staged_materials = load_task(
            config.output_root / "native-task", tool_contract=tools
        )
        consumed = load_cases(staged_materials, ("fresh",))
        assert consumed[0].input["item"] == f"revision-{revision}"
        recorded = json.loads(
            (config.output_root / manifest["case_snapshot"]["ref"]).read_bytes()
        )
        assert (
            recorded == cases and manifest["case_snapshot"]["schema_version"] == "1.0"
        )
        assert manifest["case_ids"] == ["fresh"] and manifest["model_calls"] == 0
        manifests.append(manifest)
    shutil.rmtree(task)
    for revision, manifest in enumerate(manifests):
        for role in ("rubric_snapshot", "case_snapshot"):
            assert (tmp_path / f"run-{revision}" / manifest[role]["ref"]).is_file()
            assert manifests[0][role]["sha256"] != manifests[1][role]["sha256"]


@pytest.mark.parametrize("invalid", ["schema", "ports"])
def test_cli_preflight_preserves_safe_reason_without_starting_a_run(
    tmp_path: Path, config_data: dict, invalid: str, native_task_files
) -> None:
    import subprocess
    import sys

    marker = "private-token-do-not-print"
    config_path = tmp_path / (marker + ".json")
    if invalid == "schema":
        config_path.write_text("{}")
        code = "invalid_schema"
    else:
        config_data["broker_port"] = config_data["tools_port"]
        config_path.write_text(json.dumps(config_data))
        code = "invalid_ports"
    output = tmp_path / marker
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "workflow_bench.cli",
            "--task",
            str(native_task_files[0]),
            "--config",
            str(config_path),
            "--output",
            str(output),
            "--case",
            "fresh",
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and not result.stdout
    assert code in result.stderr and "e1_config" in result.stderr
    assert marker not in result.stderr and "Traceback" not in result.stderr
    assert config_data["app_image"] not in result.stderr
    assert not output.exists()


@pytest.mark.parametrize(
    "failure,code",
    [
        ("artifact", "invalid_graph"),
        ("unexpected", "unexpected_error"),
        ("unavailable", "missing_evaluation"),
    ],
)
def test_cli_failure_keeps_safe_code_and_existing_log_reference(
    tmp_path: Path, config_data: dict, failure: str, code: str, native_task_files
) -> None:
    import subprocess
    import sys

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    output = tmp_path / "run"
    script = """
import sys
import logging
from pathlib import Path
from harbor.trial.trial import Trial
from types import SimpleNamespace
from workflow_bench import cli, experiment, harbor
from workflow_bench.execution import ArtifactError
task_path, tools_path, config_path, output, failure = sys.argv[1:]
async def tools(config, **kwargs):
    return Path(tools_path)
async def fail(config):
    (Path(output) / "harbor").mkdir()
    if failure == "artifact":
        raise ArtifactError("invalid_graph")
    if failure == "unavailable":
        async def run():
            return SimpleNamespace(exception_info=None)
        paths = SimpleNamespace(trial_dir=Path(output) / "harbor/trial",
                                verifier_dir=Path(output) / "harbor/trial/verifier",
                                result_path=Path(output) / "harbor/trial/result.json")
        return SimpleNamespace(paths=paths, run=run, add_hook=lambda *args: None)
    logging.getLogger("harbor.utils.logger").debug("private-input expected-value secret-token")
    raise RuntimeError("private-input expected-value secret-token")
async def docker(*args):
    return ""
harbor.docker = docker
experiment.tool_contract = tools
Trial.create = fail
sys.argv = ["cli", "--task", task_path,
            "--config", config_path, "--output", output, "--case", "fresh"]
cli.main()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(native_task_files[0]),
            str(native_task_files[1]),
            str(config_path),
            str(output),
            failure,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0 and not result.stdout
    assert f"code={code}" in result.stderr and "log_ref=harbor" in result.stderr
    assert all(
        value not in result.stderr
        for value in ("private-input", "expected-value", "secret-token", "Traceback")
    )
    assert (output / "report.json").exists()
    if failure == "unavailable":
        assert (
            json.loads((output / "report.json").read_bytes())["completeness"]
            == "unavailable"
        )


def test_preparation_does_not_hide_an_unsafe_source_behind_a_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config_data: dict,
    native_task_files,
) -> None:
    from workflow_bench.data import DataError

    task, tools = native_task_files
    instruction = task / "instruction.md"
    target = tmp_path / "outside.md"
    instruction.rename(target)
    instruction.symlink_to(target)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path / "run")

    async def exported_tools(config, **kwargs):
        return tools

    async def observe_preparation(native_config):
        raise PreparationObserved()

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    monkeypatch.setattr(Trial, "create", observe_preparation)
    with pytest.raises(DataError) as error:
        asyncio.run(run_manual(task, ("fresh",), config=config))
    assert error.value.code == "unsafe_path"
    assert not (config.output_root / "manifest.json").exists()
