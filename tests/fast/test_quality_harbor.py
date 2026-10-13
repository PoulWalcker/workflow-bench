"""Fast checks of Docker metadata and cleanup decisions."""

import asyncio
from collections.abc import Mapping
from typing import cast

import pytest
from harbor.environments.base import BaseEnvironment

from workflow_bench.harbor import LifecycleFacts, _cleanup, assert_stopped, docker


class _DockerProcess:
    def __init__(self, output: str, returncode: int = 0) -> None:
        self.output = output
        self.returncode = returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.output.encode(), b""

    def kill(self) -> None:
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode


def _substitute_docker(
    monkeypatch: pytest.MonkeyPatch,
    responses: Mapping[str, str],
    *,
    returncode: int = 0,
) -> None:
    async def start(*command: str, **_options: object) -> _DockerProcess:
        assert command[0] == "docker"
        return _DockerProcess(responses.get(command[1], ""), returncode)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)


def test_docker_returns_trimmed_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _substitute_docker(monkeypatch, {"ps": "container-1\n"})

    assert asyncio.run(docker("ps")) == "container-1"


def test_docker_rejects_failed_metadata_query(monkeypatch: pytest.MonkeyPatch) -> None:
    _substitute_docker(monkeypatch, {}, returncode=1)

    with pytest.raises(RuntimeError, match="^docker_metadata_failed$"):
        asyncio.run(docker("ps"))


class _StopEnvironment:
    def __init__(self, *, fails: bool = False) -> None:
        self.fails = fails

    async def stop(self, delete: bool) -> None:
        if self.fails:
            raise RuntimeError("private stop detail")


def test_cleanup_confirms_no_owned_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    _substitute_docker(monkeypatch, {})
    lifecycle = LifecycleFacts()

    is_clean = asyncio.run(
        _cleanup(
            cast(BaseEnvironment, _StopEnvironment()),
            "trial-a",
            cleanup_timeout_sec=1,
            lifecycle=lifecycle,
        )
    )

    assert is_clean
    assert lifecycle.cleanup_errors == []
    assert lifecycle.residual_resources == []


def test_cleanup_records_stop_failure_and_residuals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _substitute_docker(monkeypatch, {"ps": "container-1\n"})
    lifecycle = LifecycleFacts()

    is_clean = asyncio.run(
        _cleanup(
            cast(BaseEnvironment, _StopEnvironment(fails=True)),
            "trial-a",
            cleanup_timeout_sec=1,
            lifecycle=lifecycle,
        )
    )

    assert not is_clean
    assert lifecycle.cleanup_errors == ["trial-a:stop_failed:RuntimeError"]
    assert lifecycle.residual_resources == ["container:container-1"]


def test_cleanup_marks_failed_inspection_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _substitute_docker(monkeypatch, {}, returncode=1)
    lifecycle = LifecycleFacts()

    is_clean = asyncio.run(
        _cleanup(None, "trial-a", cleanup_timeout_sec=1, lifecycle=lifecycle)
    )

    assert not is_clean
    assert lifecycle.cleanup_errors == ["trial-a:inspection_failed:RuntimeError"]
    assert lifecycle.residual_resources == ["project:trial-a:unknown"]


def test_assert_stopped_ignores_other_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _substitute_docker(monkeypatch, {"ps": "other-service\n"})

    asyncio.run(assert_stopped("trial-a", services={"candidate"}))


def test_assert_stopped_rejects_requested_active_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _substitute_docker(monkeypatch, {"ps": "candidate\n"})

    with pytest.raises(RuntimeError, match="^stop_unconfirmed$"):
        asyncio.run(assert_stopped("trial-a", services={"candidate"}))


def test_assert_stopped_checks_deleted_project_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _substitute_docker(monkeypatch, {"network": "trial-network\n"})

    with pytest.raises(RuntimeError, match="^cleanup_incomplete$"):
        asyncio.run(assert_stopped("trial-a", deleted=True))
