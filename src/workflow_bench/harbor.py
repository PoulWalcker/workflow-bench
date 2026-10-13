"""Bound native Harbor Docker teardown and confirm owned resources stopped."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, override

from harbor.environments.base import BaseEnvironment, ExecResult, OutputCallback
from harbor.environments.docker.docker import DockerEnvironment

LOGGER = logging.getLogger(__name__)


class DeadlineDockerEnvironment(DockerEnvironment):
    """Bound native teardown, including Harbor's shielded finalization calls."""

    def __init__(self, *, cleanup_timeout_sec: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.cleanup_timeout_sec = cleanup_timeout_sec
        self.cancel_writer: Callable[[], Awaitable[None]] | None = None
        self._stopping_writer = False

    @override
    async def stop(self, delete: bool) -> None:
        async with asyncio.timeout(self.cleanup_timeout_sec):
            await super().stop(delete=delete)

    @override
    async def _collect_buffered_output(
        self,
        process: asyncio.subprocess.Process,
        *,
        timeout_sec: int | None,
        stdin_data: bytes | None = None,
    ) -> ExecResult:
        return await self._collect_with_stop(
            super()._collect_buffered_output(
                process, timeout_sec=timeout_sec, stdin_data=stdin_data
            ),
            process,
        )

    @override
    async def _collect_streamed_output(
        self,
        process: asyncio.subprocess.Process,
        *,
        timeout_sec: int | None,
        stdin_data: bytes | None = None,
        on_output: OutputCallback,
    ) -> ExecResult:
        return await self._collect_with_stop(
            super()._collect_streamed_output(
                process,
                timeout_sec=timeout_sec,
                stdin_data=stdin_data,
                on_output=on_output,
            ),
            process,
        )

    async def _collect_with_stop(
        self,
        collection: Awaitable[ExecResult],
        process: asyncio.subprocess.Process,
    ) -> ExecResult:
        pending = asyncio.create_task(collection)
        try:
            # Stop the container before Harbor's collector cancellation and the
            # installed agent's finally blocks. Both can otherwise leave children.
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            if self.cancel_writer is not None and not self._stopping_writer:
                self._stopping_writer = True
                try:
                    async with asyncio.timeout(self.cleanup_timeout_sec):
                        await self.cancel_writer()
                finally:
                    self._stopping_writer = False
            raise
        finally:
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            pending.cancel()
            async with asyncio.timeout(self.cleanup_timeout_sec):
                await asyncio.gather(pending, return_exceptions=True)
                if process.returncode is None:
                    await process.communicate()


@dataclass
class LifecycleFacts:
    cleanup_errors: list[str] = field(default_factory=list)
    residual_resources: list[str] = field(default_factory=list)


async def _cleanup(
    environment: BaseEnvironment | None,
    project: str,
    *,
    cleanup_timeout_sec: float,
    lifecycle: LifecycleFacts,
) -> bool:
    try:
        async with asyncio.timeout(cleanup_timeout_sec):
            if environment is not None:
                await environment.stop(delete=True)
    except Exception as error:
        lifecycle.cleanup_errors.append(f"{project}:stop_failed:{type(error).__name__}")
    residuals = []
    try:
        async with asyncio.timeout(cleanup_timeout_sec):
            for kind, arguments in (
                ("container", ["ps", "-a", "--format", "{{.ID}}"]),
                ("network", ["network", "ls", "--format", "{{.Name}}"]),
                ("volume", ["volume", "ls", "--format", "{{.Name}}"]),
            ):
                resources = await docker(
                    *arguments,
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                )
                residuals.extend(f"{kind}:{name}" for name in resources.splitlines())
    except Exception as error:
        lifecycle.cleanup_errors.append(
            f"{project}:inspection_failed:{type(error).__name__}"
        )
        residuals.append(f"project:{project}:unknown")
    lifecycle.residual_resources.extend(residuals)
    if residuals:
        LOGGER.warning("phase=cleanup project=%s result=incomplete", project)
    return not residuals


async def docker(*arguments: str) -> str:
    """A bounded Docker metadata query, never a second lifecycle implementation."""
    process = await asyncio.create_subprocess_exec(
        "docker",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(10):
            stdout, _ = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode:
        raise RuntimeError("docker_metadata_failed")
    return stdout.decode().strip()


async def assert_stopped(
    project: str, *, services: set[str] | None = None, deleted: bool = False
) -> None:
    arguments = (
        ["ps"]
        + (["-a"] if deleted else [])
        + [
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--format",
            '{{.Label "com.docker.compose.service"}}',
        ]
    )
    active = set((await docker(*arguments)).splitlines())
    if active if services is None else active & services:
        raise RuntimeError("stop_unconfirmed")
    if deleted:
        for kind in ("network", "volume"):
            if await docker(
                kind,
                "ls",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--format",
                "{{.Name}}",
            ):
                raise RuntimeError("cleanup_incomplete")
