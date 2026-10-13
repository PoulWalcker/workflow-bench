import asyncio
import os
import signal
from pathlib import Path

import pytest
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig
from harbor.models.trial.paths import TrialPaths

from workflow_bench.harbor import DeadlineDockerEnvironment


def test_native_stop_has_a_deadline_even_inside_harbor_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def stalled_stop(self: DockerEnvironment, delete: bool) -> None:
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
    marker = tmp_path / "pid"
    command = tmp_path / "docker"
    command.write_text(f'#!/bin/sh\necho $$ > "{marker}"\nexec sleep 60\n')
    command.chmod(0o700)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])

    async def prepared(self: DockerEnvironment) -> None:
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
