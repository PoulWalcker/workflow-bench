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
from workflow_bench.experiment import run_manual

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def config_data() -> dict:
    return {
        "app_image": "sha256:" + "a" * 64,
        "n8n_image": "sha256:" + "b" * 64,
        "runner_image": "sha256:" + "c" * 64,
        "setup_timeout_sec": 90,
        "submission_timeout_sec": 20,
        "execute_timeout_sec": 45,
        "tool_timeout_sec": 5,
        "control_timeout_sec": 10,
        "drain_timeout_sec": 10,
        "verifier_timeout_sec": 30,
        "cleanup_timeout_sec": 25,
        "total_timeout_sec": 360,
        "cpus": 1,
        "memory_mb": 1024,
        "max_calls": 8,
        "tools_port": 8080,
        "control_port": 8081,
        "broker_port": 5679,
    }


class PreparationObserved(Exception):
    pass


def test_manifest_identifies_consumed_private_snapshots_after_source_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_data: dict
) -> None:
    task = tmp_path / "task"
    shutil.copytree(ROOT / "tasks/t1-send-message", task)
    tools = ROOT / "simapps/telegram/tools.json"
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path / "run-0")

    async def exported_tools(config):
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
        cases["cases"][0]["input"]["text"] = f"revision-{revision}"
        cases_path.write_text(json.dumps(cases))
        config = replace(config, output_root=tmp_path / f"run-{revision}")
        with pytest.raises(PreparationObserved):
            asyncio.run(run_manual(task, ("fresh-a",), config=config))
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
        consumed = load_cases(staged_materials, ("fresh-a",))
        assert consumed[0].input["text"] == f"revision-{revision}"
        recorded = json.loads(
            (config.output_root / manifest["case_snapshot"]["ref"]).read_bytes()
        )
        assert (
            recorded == cases and manifest["case_snapshot"]["schema_version"] == "1.0"
        )
        assert manifest["case_ids"] == ["fresh-a"] and manifest["model_calls"] == 0
        manifests.append(manifest)
    shutil.rmtree(task)
    for revision, manifest in enumerate(manifests):
        for role in ("rubric_snapshot", "case_snapshot"):
            assert (tmp_path / f"run-{revision}" / manifest[role]["ref"]).is_file()
            assert manifests[0][role]["sha256"] != manifests[1][role]["sha256"]


@pytest.mark.parametrize("invalid", ["schema", "ports"])
def test_cli_preflight_preserves_safe_reason_without_starting_a_run(
    tmp_path: Path, config_data: dict, invalid: str
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
            str(ROOT / "tasks/t1-send-message"),
            "--config",
            str(config_path),
            "--output",
            str(output),
            "--case",
            "fresh-a",
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
    tmp_path: Path, config_data: dict, failure: str, code: str
) -> None:
    import subprocess
    import sys

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    output = tmp_path / "run"
    script = """
import sys
from pathlib import Path
from harbor.trial.trial import Trial
from types import SimpleNamespace
from workflow_bench import cli, experiment, harbor
from workflow_bench.execution import ArtifactError
root, config_path, output, failure = sys.argv[1:]
async def tools(config):
    return Path(root) / "simapps/telegram/tools.json"
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
    raise RuntimeError("private-input expected-value secret-token")
async def docker(*args):
    return ""
harbor.docker = docker
experiment.tool_contract = tools
Trial.create = fail
sys.argv = ["cli", "--task", str(Path(root) / "tasks/t1-send-message"),
            "--config", config_path, "--output", output, "--case", "fresh-a"]
cli.main()
"""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(ROOT),
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
    assert (output / "report.json").exists() == (failure == "unavailable")


def test_preparation_does_not_hide_an_unsafe_source_behind_a_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_data: dict
) -> None:
    from workflow_bench.data import DataError

    task = tmp_path / "task"
    shutil.copytree(ROOT / "tasks/t1-send-message", task)
    instruction = task / "instruction.md"
    target = tmp_path / "outside.md"
    instruction.rename(target)
    instruction.symlink_to(target)
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config_data))
    config = load_config(config_path, output=tmp_path / "run")

    async def exported_tools(config):
        return ROOT / "simapps/telegram/tools.json"

    async def observe_preparation(native_config):
        raise PreparationObserved()

    monkeypatch.setattr("workflow_bench.experiment.tool_contract", exported_tools)
    monkeypatch.setattr(Trial, "create", observe_preparation)
    with pytest.raises(DataError) as error:
        asyncio.run(run_manual(task, ("fresh-a",), config=config))
    assert error.value.code == "unsafe_path"
    assert not (config.output_root / "manifest.json").exists()
