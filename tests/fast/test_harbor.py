import asyncio
import json
import os
from pathlib import Path

import pytest
from harbor.environments.base import ExecResult
from harbor.environments.docker.docker import DockerEnvironment

from workflow_bench.cli import load_config
from workflow_bench.harbor import tool_contract


def test_failed_submission_cannot_supply_trusted_evaluation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_data: dict
) -> None:
    import shutil
    from types import SimpleNamespace

    from harbor.trial.trial import Trial

    from workflow_bench.harbor import run_native_trial

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    config = load_config(path, output=tmp_path)
    stage = tmp_path / "task"
    shutil.copytree(
        Path(__file__).resolve().parents[2] / "tasks/t1-send-message", stage
    )
    verifier = tmp_path / "harbor/trial/verifier"
    verifier.mkdir(parents=True)
    forged = {
        "identity": {
            "run_id": "forged",
            "attempt_id": "forged",
            "replay_id": "forged",
            "case_id": "forged",
            "artifact_hash": "a" * 64,
            "profile_hash": "b" * 64,
            "profile": "t1-api-v1",
        },
        "score": None,
        "verdict": "unknown",
        "completeness": "complete",
        "criteria": [],
        "violations": [],
        "errors": [],
        "evidence_hash": None,
    }
    (verifier / "evaluation.json").write_text(
        json.dumps({"schema_version": "1.0", "cases": [forged]})
    )

    async def run():
        return SimpleNamespace(
            exception_info=SimpleNamespace(exception_type="RuntimeError"),
            verifier_result=None,
        )

    async def create(config):
        return SimpleNamespace(
            paths=SimpleNamespace(
                trial_dir=verifier.parent,
                verifier_dir=verifier,
                result_path=verifier.parent / "result.json",
            ),
            add_hook=lambda *args: None,
            run=run,
        )

    async def prepare(path):
        pytest.fail("failed submission must not replay")

    command = tmp_path / "docker"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setattr(Trial, "create", create)
    result = asyncio.run(run_native_trial(stage, "failed", prepare, config=config))
    assert result.evaluation["cases"] == []


def test_native_stop_has_a_deadline_even_inside_harbor_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    from workflow_bench.harbor import DeadlineDockerEnvironment

    async def stalled_stop(self, delete):
        await asyncio.Event().wait()

    monkeypatch.setattr(DockerEnvironment, "stop", stalled_stop)
    environment = DeadlineDockerEnvironment(
        environment_dir=tmp_path,
        environment_name="bounded",
        session_id="bounded",
        trial_paths=TrialPaths(trial_dir=tmp_path / "harbor"),
        task_env_config=EnvironmentConfig(docker_image="synthetic"),
        cleanup_timeout_sec=0.01,
    )
    with pytest.raises(TimeoutError):
        asyncio.run(environment.stop(delete=True))


def test_native_stop_timeout_reaps_its_docker_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import signal

    from harbor.models.task.config import EnvironmentConfig
    from harbor.models.trial.paths import TrialPaths

    from workflow_bench.harbor import DeadlineDockerEnvironment

    marker = tmp_path / "pid"
    command = tmp_path / "docker"
    command.write_text(f'#!/bin/sh\necho $$ > "{marker}"\nexec sleep 60\n')
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    async def prepared(self):
        pass

    monkeypatch.setattr(DockerEnvironment, "prepare_logs_for_host", prepared)
    environment = DeadlineDockerEnvironment(
        environment_dir=tmp_path,
        environment_name="bounded",
        session_id="bounded",
        trial_paths=TrialPaths(trial_dir=tmp_path / "harbor"),
        task_env_config=EnvironmentConfig(docker_image="synthetic"),
        cleanup_timeout_sec=1,
    )
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(environment.stop(delete=True))
        pid = int(marker.read_text())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        if marker.exists():
            try:
                os.kill(int(marker.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_failed_cleanup_records_owned_residuals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_data: dict
) -> None:
    from workflow_bench.data import DataError
    from workflow_bench.harbor import LifecycleFacts

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    config = load_config(path, output=tmp_path / "run")
    config.output_root.mkdir()
    command = tmp_path / "docker"
    command.write_text('#!/bin/sh\ncase "$1" in ps) echo owned-container;; esac\n')
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    async def start(self, **kwargs):
        pass

    async def stop(self, **kwargs):
        raise RuntimeError("private transport detail")

    async def execute(self, command, *, timeout_sec):
        return ExecResult(stdout="{}", return_code=0)

    monkeypatch.setattr(DockerEnvironment, "start", start)
    monkeypatch.setattr(DockerEnvironment, "stop", stop)
    monkeypatch.setattr(DockerEnvironment, "exec", execute)
    facts = LifecycleFacts()
    with pytest.raises(DataError, match="cleanup_incomplete"):
        asyncio.run(tool_contract(config, lifecycle=facts))
    assert any("stop_failed" in error for error in facts.cleanup_errors)
    assert "container:owned-container" in facts.residual_resources
    assert all("private" not in error for error in facts.cleanup_errors)


def test_failed_revoke_still_stops_both_execution_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_data: dict
) -> None:
    from types import SimpleNamespace

    from aiohttp import ClientConnectionError

    from workflow_bench.harbor import ReplayContext

    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    config = load_config(path, output=tmp_path)

    async def check():
        services = {"n8n", "runner"}

        async def stop_service(service):
            services.remove(service)

        class Unavailable:
            async def __aenter__(self):
                raise ClientConnectionError()

            async def __aexit__(self, *args):
                pass

        command = tmp_path / "docker"
        command.write_text("#!/bin/sh\nexit 0\n")
        command.chmod(0o700)
        monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
        context = ReplayContext(
            SimpleNamespace(stop_service=stop_service),
            SimpleNamespace(request=lambda *args, **kwargs: Unavailable()),
            "http://unavailable",
            "secret",
            {"case_id": "test"},
            tmp_path,
            "owned",
            config,
        )
        assert await context.finish() is True
        assert not services
        assert json.loads((tmp_path / "stop.json").read_text())["errors"]

    asyncio.run(check())


def test_fractional_deadline_keeps_native_exec_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, config_data: dict
) -> None:
    config_data["control_timeout_sec"] = 0.5
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config_data))
    config = load_config(path, output=tmp_path / "run")
    config.output_root.mkdir()
    command = tmp_path / "docker"
    command.write_text("#!/bin/sh\nexit 0\n")
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    async def start(self, **kwargs):
        pass

    async def stop(self, **kwargs):
        pass

    async def execute(self, command, *, timeout_sec):
        assert timeout_sec == 1
        return ExecResult(stdout="{}", return_code=0)

    monkeypatch.setattr(DockerEnvironment, "start", start)
    monkeypatch.setattr(DockerEnvironment, "stop", stop)
    monkeypatch.setattr(DockerEnvironment, "exec", execute)
    assert asyncio.run(tool_contract(config)).read_text() == "{}"
