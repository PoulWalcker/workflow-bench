"""Own native Harbor environments and the protected simulator control channel."""

import asyncio
import json
import logging
import secrets
import shlex
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout
from harbor.environments.base import BaseEnvironment
from harbor.environments.docker.docker import DockerEnvironment
from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
from harbor.models.task.task import Task
from harbor.models.trial.config import TrialConfig
from harbor.models.trial.paths import TrialPaths
from harbor.trial.hooks import TrialEvent, TrialHookEvent
from harbor.trial.trial import Trial

from workflow_bench.contracts import E1Config, JsonValue
from workflow_bench.data import (
    MAX_EVIDENCE_BYTES,
    MAX_JSON_BYTES,
    decode_json,
    read_json,
    validate_contract,
)

LOGGER = logging.getLogger(__name__)


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


async def _check_private_access(
    environment: BaseEnvironment, *, timeout_sec: float, service: str | None = None
) -> None:
    command = 'set -eu; test ! -e /tests; test ! -e /solution; test ! -e /bench/input; test ! -e /var/run/docker.sock; test ! -e /app/workflow_bench/experiment.py; test -z "${WB_CONTROL_KEY:-}"'
    checked = (
        await environment.exec(command, timeout_sec=int(timeout_sec))
        if service is None
        else await environment.service_exec(
            command, service=service, timeout_sec=int(timeout_sec)
        )
    )
    if checked.return_code:
        raise RuntimeError(
            "submission_isolation_failed" if service is None else "isolation_failed"
        )


@dataclass(frozen=True)
class NativeVerification:
    evaluation: dict[str, JsonValue]
    exception_type: str | None
    result_ref: str


async def run_native_trial(
    stage: Path,
    attempt_id: str,
    prepare_verification: Callable[[Path], Awaitable[None]],
    *,
    config: E1Config,
) -> NativeVerification:
    """Collect after confirmed stop; deliver prepared inputs via native tests upload.

    The callback receives the checked submission path at VERIFICATION_START,
    before the separate verifier is created. It writes protected inputs under
    the staged Task tests; it never receives the Trial or a container handle.
    """
    native = Task(task_dir=stage).config.model_copy(deep=True)
    native.environment.docker_image = config.app_image
    native.environment.cpus = config.cpus
    native.environment.memory_mb = config.memory_mb
    native.environment.build_timeout_sec = config.setup_timeout_sec
    native.agent.timeout_sec = config.submission_timeout_sec
    native.verifier.timeout_sec = config.verifier_timeout_sec
    (stage / "task.toml").write_text(native.model_dump_toml())
    trial_name = "wb04-manual-" + attempt_id
    trial_config = TrialConfig.model_validate(
        {
            "task": {"path": str(stage)},
            "trial_name": trial_name,
            "trials_dir": str(config.output_root / "harbor"),
            "agent": {
                "name": "oracle",
                "override_timeout_sec": config.submission_timeout_sec,
            },
            "verifier": {"override_timeout_sec": config.verifier_timeout_sec},
            "environment": {
                "delete": True,
                "override_cpus": config.cpus,
                "override_memory_mb": config.memory_mb,
            },
        }
    )
    trial = await Trial.create(trial_config)

    async def check_submission(event: TrialHookEvent) -> None:
        await _check_private_access(
            trial.agent_environment, timeout_sec=config.control_timeout_sec
        )
        LOGGER.info("phase=isolation submission=%s result=confirmed", event.trial_name)

    async def collected(event: TrialHookEvent) -> None:
        LOGGER.info("phase=submission result=collected")
        await assert_stopped(event.trial_name + "__env", deleted=True)
        manifest = read_json(trial.paths.artifacts_dir / "manifest.json", "collection")
        if not any(
            item["source"] == "/work/workflow.json"
            and item["status"] == "ok"
            and item["type"] == "file"
            for item in manifest
        ):
            raise RuntimeError("artifact_collection_failed")
        await prepare_verification(trial.paths.artifacts_dir / "work/workflow.json")

    trial.add_hook(TrialEvent.AGENT_START, check_submission)
    trial.add_hook(TrialEvent.VERIFICATION_START, collected)
    LOGGER.info(
        "phase=submission attempt_id=%s log=%s", attempt_id, trial.paths.trial_dir
    )
    native_result = await trial.run()
    await assert_stopped(trial_name + "__env", deleted=True)
    await assert_stopped(trial_name + "__verifier__trial", deleted=True)
    path = trial.paths.verifier_dir / "evaluation.json"
    evaluation = (
        read_json(path, "evaluation")
        if path.exists()
        else {"schema_version": "1.0", "cases": []}
    )
    for result in evaluation["cases"]:
        validate_contract("evaluation", result)
    return NativeVerification(
        evaluation,
        native_result.exception_info.exception_type
        if native_result.exception_info
        else None,
        str(trial.paths.result_path.relative_to(config.output_root)),
    )


@dataclass(frozen=True)
class ReplayContext:
    environment: BaseEnvironment
    session: ClientSession
    control_url: str
    control_key: str
    identity: dict[str, str]
    root: Path
    project: str
    config: E1Config

    async def check_isolation(self) -> None:
        """Check the actual replay surfaces before uploading untrusted JSON."""
        for service in ("n8n", "runner"):
            await _check_private_access(
                self.environment,
                timeout_sec=self.config.control_timeout_sec,
                service=service,
            )
        fresh = await self.environment.service_exec(
            "test ! -e /home/node/.n8n/database.sqlite",
            service="n8n",
            timeout_sec=int(self.config.control_timeout_sec),
        )
        if fresh.return_code:
            raise RuntimeError("replay_database_not_fresh")
        main = await docker(
            "ps",
            "--filter",
            f"label=com.docker.compose.project={self.project}",
            "--filter",
            "label=com.docker.compose.service=main",
            "--format",
            "{{.ID}}",
        )
        networks = json.loads(
            await docker(
                "inspect", main, "--format", "{{json .NetworkSettings.Networks}}"
            )
        )
        control_ip = networks[self.project + "_management"]["IPAddress"]
        targets = [
            f"http://{control_ip}:{self.config.control_port}/control/export",
            f"http://simulator:{self.config.control_port}/control/export",
        ]
        probe = (
            "Promise.all("
            + json.dumps(targets)
            + ".map(u=>fetch(u,{signal:AbortSignal.timeout(1000)}).then(()=>true,()=>false))).then(r=>process.exit(r.some(Boolean)?1:0))"
        )
        for service in ("n8n", "runner"):
            container = await docker(
                "ps",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
                "--filter",
                f"label=com.docker.compose.service={service}",
                "--format",
                "{{.ID}}",
            )
            info = json.loads(await docker("inspect", container))[0]
            if any(mount["Type"] == "bind" for mount in info["Mounts"]):
                raise RuntimeError("replay_bind_mount_forbidden")
            if any(info["NetworkSettings"]["Ports"].values()):
                raise RuntimeError("replay_port_exposed")
            for network in info["NetworkSettings"]["Networks"].values():
                if (
                    await docker(
                        "network",
                        "inspect",
                        network["NetworkID"],
                        "--format",
                        "{{.Internal}}",
                    )
                    != "true"
                ):
                    raise RuntimeError("replay_network_not_internal")
            checked = await self.environment.service_exec(
                "node -e " + shlex.quote(probe),
                service=service,
                timeout_sec=int(self.config.control_timeout_sec),
            )
            if checked.return_code:
                raise RuntimeError("replay_control_reachable")
        LOGGER.info(
            "phase=isolation case_id=%s result=confirmed", self.identity["case_id"]
        )

    async def control(self, operation: str, data: JsonValue = None) -> JsonValue:
        method = "GET" if operation == "export" else "POST"
        async with self.session.request(
            method,
            self.control_url + "/control/" + operation,
            json=data,
            headers={"Authorization": "Bearer " + self.control_key},
        ) as response:
            if response.status != 200:
                raise RuntimeError("control_failed")
            chunks = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                chunks.extend(chunk)
                if len(chunks) > (
                    MAX_EVIDENCE_BYTES if operation == "export" else MAX_JSON_BYTES
                ):
                    raise RuntimeError("control_too_large")
            return decode_json(bytes(chunks), "control")

    async def finish(self) -> None:
        """Seal admission and facts, stop both untrusted services, confirm stop."""
        await self.control("revoke", {"identity": self.identity})
        async with asyncio.timeout(self.config.drain_timeout_sec):
            await self.control(
                "freeze",
                {"identity": self.identity, "drain_sec": self.config.drain_timeout_sec},
            )
        async with asyncio.timeout(self.config.cleanup_timeout_sec):
            await self.environment.stop_service("n8n")
            await self.environment.stop_service("runner")
            await assert_stopped(self.project, services={"n8n", "runner"})


async def tool_contract(config: E1Config) -> Path:
    root = config.output_root / "profile-export"
    root.mkdir()
    paths = TrialPaths(trial_dir=root / "harbor")
    paths.trial_dir.mkdir()
    project = "wb04-profile-" + secrets.token_hex(8)
    policy = NetworkPolicy(network_mode=NetworkMode.NO_NETWORK)
    environment = DockerEnvironment(
        environment_dir=root,
        environment_name="profile-export",
        session_id=project,
        trial_paths=paths,
        task_env_config=EnvironmentConfig(
            docker_image=config.app_image, cpus=config.cpus, memory_mb=config.memory_mb
        ),
        mounts=[],
        network_policy=policy,
        enable_environment_dir_upload=False,
    )
    try:
        async with asyncio.timeout(config.setup_timeout_sec):
            await environment.start(force_build=False)
            exported = await environment.exec(
                "cat /bench/tools.json", timeout_sec=int(config.control_timeout_sec)
            )
            if exported.return_code:
                raise RuntimeError("tool_contract_export_failed")
            destination = root / "tools.json"
            destination.write_text(exported.stdout)
            return destination
    finally:
        async with asyncio.timeout(config.cleanup_timeout_sec):
            await environment.stop(delete=True)
            await assert_stopped(project, deleted=True)


@asynccontextmanager
async def replay_environment(
    config: E1Config, identity: dict[str, str]
) -> AsyncIterator[ReplayContext]:
    project = "wb04-replay-" + identity["replay_id"]
    root = config.output_root / project
    root.mkdir(mode=0o700)
    environment_dir = root / "environment"
    environment_dir.mkdir()
    key, broker_key = secrets.token_hex(32), secrets.token_hex(32)
    common = {
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges:true"],
        "read_only": True,
        "tmpfs": ["/tmp"],
        "cpus": config.cpus,
        "mem_limit": f"{config.memory_mb}m",
    }
    compose = {
        "services": {
            "main": {
                **common,
                "image": config.app_image,
                "command": ["python", "/bench/simulator.py"],
                "environment": {
                    "WB_CONTROL_KEY": key,
                    "WB_TOOLS_PORT": str(config.tools_port),
                    "WB_CONTROL_PORT": str(config.control_port),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                "ports": [f"127.0.0.1::{config.control_port}"],
                "networks": {
                    "management": {"aliases": ["control"], "gw_priority": 1},
                    "tools": {"aliases": ["simulator"]},
                },
            },
            "n8n": {
                **common,
                "image": config.n8n_image,
                "entrypoint": ["/bin/sh", "-c"],
                "command": ["sleep infinity"],
                "user": "node",
                "volumes": ["database:/home/node/.n8n"],
                "networks": ["tools", "broker"],
                "environment": {
                    "N8N_RUNNERS_MODE": "external",
                    "N8N_RUNNERS_AUTH_TOKEN": broker_key,
                    "N8N_RUNNERS_BROKER_LISTEN_ADDRESS": "0.0.0.0",
                    "N8N_RUNNERS_BROKER_PORT": str(config.broker_port),
                    "N8N_RUNNERS_TASK_TIMEOUT": str(int(config.execute_timeout_sec)),
                    "N8N_RUNNERS_TASK_REQUEST_TIMEOUT": str(
                        int(config.execute_timeout_sec)
                    ),
                    "N8N_DIAGNOSTICS_ENABLED": "false",
                    "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
                    "N8N_BLOCK_ENV_ACCESS_IN_NODE": "true",
                    "N8N_BLOCK_FILE_ACCESS_TO_N8N_FILES": "true",
                    "N8N_COMMUNITY_PACKAGES_ENABLED": "false",
                    "N8N_PERSONALIZATION_ENABLED": "false",
                    "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS": "true",
                    "N8N_SSRF_PROTECTION_ENABLED": "false",
                },
            },
            "runner": {
                **common,
                "image": config.runner_image,
                "networks": ["broker"],
                "environment": {
                    "N8N_RUNNERS_AUTH_TOKEN": broker_key,
                    "N8N_RUNNERS_TASK_BROKER_URI": f"http://n8n:{config.broker_port}",
                    "N8N_RUNNERS_TASK_TIMEOUT": str(int(config.execute_timeout_sec)),
                    "N8N_RUNNERS_LAUNCHER_LOG_LEVEL": "debug",
                },
            },
        },
        "networks": {
            "management": {},
            "tools": {"internal": True},
            "broker": {"internal": True},
        },
        "volumes": {"database": {}},
    }
    compose_path = environment_dir / "docker-compose.yaml"
    compose_path.write_text(json.dumps(compose))
    compose_path.chmod(0o600)
    paths = TrialPaths(trial_dir=root / "harbor")
    paths.trial_dir.mkdir()
    environment = DockerEnvironment(
        environment_dir=environment_dir,
        environment_name="t1-replay",
        session_id=project,
        trial_paths=paths,
        task_env_config=EnvironmentConfig(
            docker_image=config.app_image, cpus=config.cpus, memory_mb=config.memory_mb
        ),
        mounts=[],
        enable_environment_dir_upload=False,
    )
    session = ClientSession(timeout=ClientTimeout(total=config.control_timeout_sec))
    try:
        LOGGER.info("phase=setup case_id=%s", identity["case_id"])
        async with asyncio.timeout(config.setup_timeout_sec):
            await environment.start(force_build=False)
            container = await docker(
                "ps",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--filter",
                "label=com.docker.compose.service=main",
                "--format",
                "{{.ID}}",
            )
            ports = json.loads(
                await docker(
                    "inspect", container, "--format", "{{json .NetworkSettings.Ports}}"
                )
            )
            bindings = ports.get(f"{config.control_port}/tcp")
            if not bindings:
                raise RuntimeError("control_binding_missing")
            binding = bindings[0]
            if binding["HostIp"] != "127.0.0.1":
                raise RuntimeError("control_binding_unsafe")
            context = ReplayContext(
                environment,
                session,
                f"http://127.0.0.1:{binding['HostPort']}",
                key,
                identity,
                root,
                project,
                config,
            )
            while True:
                try:
                    async with session.get(
                        context.control_url + "/control/export"
                    ) as response:
                        if response.status == 403:
                            break
                except ClientError:
                    pass
                await asyncio.sleep(0.1)
        yield context
    finally:
        LOGGER.info("phase=cleanup case_id=%s", identity["case_id"])
        try:
            async with asyncio.timeout(config.cleanup_timeout_sec):
                await environment.stop(delete=True)
                await assert_stopped(project, deleted=True)
                LOGGER.info(
                    "phase=cleanup case_id=%s result=confirmed", identity["case_id"]
                )
        finally:
            await session.close()
