"""Codex composition at Harbor's installed-agent seam; no agent loop."""

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import selectors
import shlex
import shutil
import stat
import subprocess
import time
from dataclasses import replace
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import override

from harbor.agents.installed.codex import Codex
from harbor.models.agent.context import AgentContext
from harbor.models.task.config import MCPServerConfig
from harbor.models.trajectories import Trajectory
from harbor.models.trial.config import AgentConfig

from workflow_bench.contracts import JsonValue
from workflow_bench.data import MAX_EVIDENCE_BYTES, DataError, decode_json, read_json
from workflow_bench.experiment import ControlledSubmission
from workflow_bench.harbor import (
    LifecycleFacts,
    docker,
    replay_environment,
    run_native_trial,
)
from workflow_bench.n8n_contracts import (
    SUBMISSION_TRIAL_PREFIX,
    E1Config,
    PublicPackage,
    WorkflowArtifact,
)

LOGGER = logging.getLogger(__name__)
STUB_BASE_URL = "http://provider:8080/v1"
MAX_SESSION_ENTRIES = 256
MAX_SESSION_DEPTH = 8


def read_codex_limits(auth_path: Path, *, timeout_sec: float) -> dict[str, JsonValue]:
    """Read the subscription's live limits in a clean, host-only native session."""
    auth = read_json(auth_path, "codex_auth")
    if not isinstance(auth, dict) or auth.get("auth_mode") != "chatgpt":
        raise DataError("chatgpt_auth_required", "codex_auth")
    with TemporaryDirectory(prefix="wb-account-") as directory:
        home = Path(directory)
        copied = home / "auth.json"
        copied.write_text(json.dumps(auth))
        copied.chmod(0o600)
        environment = dict(os.environ, CODEX_HOME=str(home))
        environment.pop("OPENAI_API_KEY", None)
        environment.pop("OPENAI_BASE_URL", None)
        process = subprocess.Popen(
            ["codex", "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        )
        deadline = time.monotonic() + timeout_sec
        buffer = b""
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)

            def request(message):
                nonlocal buffer
                process.stdin.write((json.dumps(message) + "\n").encode())
                process.stdin.flush()
                while time.monotonic() < deadline:
                    while b"\n" in buffer:
                        line, buffer = buffer.split(b"\n", 1)
                        response = json.loads(line)
                        if response.get("id") == message["id"]:
                            if "error" in response:
                                raise DataError(
                                    "subscription_status_unavailable", "codex_account"
                                )
                            return response.get("result")
                    if not selector.select(min(1, max(0, deadline - time.monotonic()))):
                        continue
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if not chunk or len(buffer) + len(chunk) > MAX_EVIDENCE_BYTES:
                        raise DataError(
                            "subscription_status_unavailable", "codex_account"
                        )
                    buffer += chunk
                raise DataError("subscription_status_timeout", "codex_account")

            try:
                request(
                    {
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "clientInfo": {"name": "workflow_bench", "version": "0.1.0"}
                        },
                    }
                )
                process.stdin.write(b'{"method":"initialized"}\n')
                process.stdin.flush()
                result = request(
                    {"id": 2, "method": "account/rateLimits/read", "params": {}}
                )
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
    if not isinstance(result, dict) or result.get("ordinaryUsageAllowed") is not True:
        raise DataError("subscription_status_unavailable", "codex_account")
    bucket = (result.get("rateLimitsByLimitId") or {}).get(
        "codex", result.get("rateLimits")
    )
    if not isinstance(bucket, dict) or not isinstance(bucket.get("primary"), dict):
        raise DataError("subscription_status_unavailable", "codex_account")
    for window in (bucket["primary"], bucket.get("secondary")):
        if window is None:
            continue
        used = window.get("usedPercent")
        if (
            isinstance(used, bool)
            or not isinstance(used, (int, float))
            or not 0 <= used <= 100
        ):
            raise DataError("subscription_status_unavailable", "codex_account")
        if used >= 100 or bucket.get("rateLimitReachedType") is not None:
            raise DataError("subscription_exhausted", "codex_account")
    # Preserve quota facts without account identifiers or auth material.
    return {"rateLimits": bucket, "observed_at_unix": time.time()}


class SessionSafeCodex(Codex):
    """Keep the stock agent loop; bound its candidate-controlled log ingestion."""

    @override
    def convert_trajectory(self, logs_dir: Path) -> Trajectory | None:
        _, snapshots, invalid = _session_snapshot(logs_dir)
        if invalid or not snapshots:
            return None
        with TemporaryDirectory(prefix="wb-session-") as directory:
            safe_logs = Path(directory)
            for reference, content in snapshots:
                target = safe_logs / reference
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            return super().convert_trajectory(safe_logs)

    @override
    def populate_context_post_run(self, context: AgentContext) -> None:
        original = self.logs_dir
        _, snapshots, invalid = _session_snapshot(original)
        if not invalid and snapshots:
            with TemporaryDirectory(prefix="wb-session-") as directory:
                self.logs_dir = Path(directory)
                try:
                    for reference, content in snapshots:
                        target = self.logs_dir / reference
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(content)
                    super().populate_context_post_run(context)
                finally:
                    self.logs_dir = original
        # Stop Trial's fallback from reading candidate trajectory.json. Empty means
        # no observed per-model records; missing token/cost fields remain unknown.
        if context.model_usage is None:
            context.model_usage = {}


def codex_preflight(
    composer: dict[str, JsonValue],
    *,
    budget: dict[str, JsonValue] | None,
    runtime: dict[str, JsonValue],
    authorized: bool,
    auth_path: Path | None = None,
) -> dict[str, JsonValue]:
    """Reject execution before credential access or resource creation."""
    required = {
        "mode",
        "image",
        "cli_version",
        "model",
        "reasoning_effort",
        "exploration_max_calls",
    }
    if (
        not isinstance(composer, dict)
        or set(composer) not in (required, required | {"authentication"})
        or not isinstance(composer["mode"], str)
        or composer["mode"] not in {"model-free", "model"}
        or not isinstance(composer["image"], str)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", composer["image"])
        or not isinstance(composer["cli_version"], str)
        or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", composer["cli_version"])
        or not isinstance(composer["model"], str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", composer["model"])
        or not isinstance(composer["reasoning_effort"], str)
        or composer["reasoning_effort"]
        not in {"none", "minimal", "low", "medium", "high", "xhigh"}
        or isinstance(composer["exploration_max_calls"], bool)
        or not isinstance(composer["exploration_max_calls"], int)
        or not 1 <= composer["exploration_max_calls"] <= 100
    ):
        raise DataError("invalid_composer_config", "composer")
    if composer["mode"] == "model-free":
        if (
            budget is not None
            or composer["model"] != "synthetic"
            or "authentication" in composer
        ):
            raise DataError("invalid_model_free_config", "composer")
        return {
            "execution_enabled": True,
            "model_calls": 0,
            "provider": "isolated_stub",
        }
    if composer.get("authentication") == "chatgpt":
        from workflow_bench.data import resource_schema, validate_json

        validate_json(runtime, resource_schema("e1.schema.json"), "e1_config")
        if not authorized:
            raise DataError("model_not_authorized", "composer")
        if auth_path is None:
            raise DataError("codex_auth_required", "composer")
        if budget is not None or composer["model"] == "synthetic":
            raise DataError("invalid_subscription_config", "composer")
        return {
            "execution_enabled": True,
            "provider": "chatgpt_subscription",
            "max_attempts": 2,
        }
    if not authorized:
        raise DataError("model_not_authorized", "composer")
    # The API-billed mode is closed: no trusted API project spending constraint is
    # verified, and a declaration in a run config cannot attest to enforcement.
    raise DataError("provider_enforcement_unverified", "model_budget")


def codex_agent_config(
    composer: dict[str, JsonValue], config: E1Config, auth_path: Path | None = None
) -> AgentConfig:
    """Native Codex configuration, also used by harnesses with internal Codex."""
    subscription = composer.get("authentication") == "chatgpt"
    agent = AgentConfig(
        import_path="workflow_bench.composer:SessionSafeCodex",
        model_name="openai/" + composer["model"],
        kwargs={
            "version": composer["cli_version"],
            "prompt_template_path": None,
            "config": {
                "web_search": "disabled",
                "model_reasoning_effort": composer["reasoning_effort"],
                "model_provider": "bench",
                "model_providers": {
                    "bench": {
                        "name": "isolated provider stub",
                        "base_url": STUB_BASE_URL,
                        "env_key": "OPENAI_API_KEY",
                        "wire_api": "responses",
                        "request_max_retries": 0,
                        "stream_max_retries": 0,
                        "stream_idle_timeout_ms": math.ceil(
                            config.submission_timeout_sec * 1000
                        ),
                    }
                },
                "features": {"multi_agent": False},
            },
        },
        env={
            "OPENAI_API_KEY": "wb-synthetic-no-provider-access",
            "OPENAI_BASE_URL": STUB_BASE_URL,
            "CODEX_AUTH_JSON_PATH": "",
            # Harbor treats AUTH flags as secrets; lowercase false would corrupt raw JSON on scrubbing.
            "CODEX_FORCE_AUTH_JSON": "False",
        },
        mcp_servers=[
            MCPServerConfig(
                name="tools",
                transport="stdio",
                command="python",
                args=[
                    "-m",
                    "workflow_bench.mcp",
                    "--contract",
                    "/work/tools.json",
                    "--connection",
                    "/work/tools-connection.json",
                    "--timeout",
                    str(config.tool_timeout_sec),
                ],
            )
        ],
    )
    if subscription:
        native_config = agent.kwargs["config"]
        native_config["model_provider"] = "chatgpt"
        native_config["model_providers"] = {
            "chatgpt": {
                "name": "OpenAI ChatGPT",
                "requires_openai_auth": True,
                "wire_api": "responses",
                "request_max_retries": 0,
                "stream_max_retries": 0,
                "stream_idle_timeout_ms": math.ceil(
                    config.submission_timeout_sec * 1000
                ),
            }
        }
        agent.env = {
            "CODEX_AUTH_JSON_PATH": str(auth_path),
            "CODEX_FORCE_AUTH_JSON": "False",
            "OPENAI_API_KEY": "",
            "OPENAI_BASE_URL": "",
        }
    return agent


async def submit_codex(
    *,
    public: PublicPackage,
    root: Path,
    run_id: str,
    attempt_id: str,
    previous: WorkflowArtifact | None,
    feedback: list[JsonValue],
    config: E1Config,
    composer: dict[str, JsonValue],
    budget: dict[str, JsonValue] | None = None,
    authorized: bool = False,
    auth_path: Path | None = None,
) -> ControlledSubmission:
    return await submit_installed(
        public=public,
        root=root,
        run_id=run_id,
        attempt_id=attempt_id,
        previous=previous,
        feedback=feedback,
        config=config,
        composer=composer,
        budget=budget,
        authorized=authorized,
        auth_path=auth_path,
        agent=codex_agent_config(composer, config, auth_path),
    )


async def submit_sapiens(
    *,
    public: PublicPackage,
    root: Path,
    run_id: str,
    attempt_id: str,
    previous: WorkflowArtifact | None,
    feedback: list[JsonValue],
    config: E1Config,
    composer: dict[str, JsonValue],
    budget: dict[str, JsonValue] | None = None,
    authorized: bool = False,
    auth_path: Path | None = None,
) -> ControlledSubmission:
    agent = codex_agent_config(composer, config, auth_path)
    agent.import_path = "workflow_bench_integrations.sapiens:SapiensInstalledAgent"
    return await submit_installed(
        public=public,
        root=root,
        run_id=run_id,
        attempt_id=attempt_id,
        previous=previous,
        feedback=feedback,
        config=config,
        composer=composer,
        budget=budget,
        authorized=authorized,
        auth_path=auth_path,
        agent=agent,
    )


async def submit_installed(
    *,
    public: PublicPackage,
    root: Path,
    run_id: str,
    attempt_id: str,
    previous: WorkflowArtifact | None,
    feedback: list[JsonValue],
    config: E1Config,
    composer: dict[str, JsonValue],
    agent: AgentConfig,
    budget: dict[str, JsonValue] | None = None,
    authorized: bool = False,
    auth_path: Path | None = None,
) -> ControlledSubmission:
    """Run one supplied installed agent in a fresh exploration world/native Trial.

    Subscription mode uses native Harbor auth and network enforcement. Credentials
    exist only during composition; Replay and independent verification never get them.
    """
    runtime = {
        key: value for key, value in vars(config).items() if key != "output_root"
    }
    codex_preflight(
        composer,
        budget=budget,
        runtime=runtime,
        authorized=authorized,
        auth_path=auth_path,
    )
    subscription = composer.get("authentication") == "chatgpt"
    limits_before = (
        await asyncio.to_thread(
            read_codex_limits, auth_path, timeout_sec=config.control_timeout_sec
        )
        if subscription
        else None
    )
    root.mkdir(mode=0o700)
    LOGGER.info("phase=creation attempt_id=%s result=started log=%s", attempt_id, root)
    creation_config = replace(config, output_root=root)
    lifecycle = LifecycleFacts()
    task = json.loads((public.root / "task.json").read_bytes())
    contract = json.loads((public.root / "tools.json").read_bytes())
    identity = {
        "run_id": run_id,
        "attempt_id": attempt_id,
        "replay_id": attempt_id,
        "case_id": "exploration",
        "artifact_hash": hashlib.sha256(b"").hexdigest(),
        "profile_hash": hashlib.sha256(
            (public.root / "tools.json").read_bytes()
        ).hexdigest(),
        "profile": contract["profile"],
    }
    stage = root / "native-task"
    (stage / "environment").mkdir(parents=True)
    shutil.copyfile(public.root / "instruction.md", stage / "instruction.md")
    handoff = root / "handoff.j2"
    handoff.write_bytes(
        files("workflow_bench").joinpath("resources/codex-handoff.j2").read_bytes()
    )
    (stage / "task.toml").write_text(
        'schema_version = "1.3"\nartifacts = ["/work/workflow.json"]\n[environment]\nworkdir = "/work"\nnetwork_mode = "no-network"\n[verifier]\nenvironment_mode = "separate"\nnetwork_mode = "no-network"\n'
    )
    # Harbor validates the Task layout even with verifier.disable=True.
    (stage / "tests").mkdir()
    (stage / "tests/test.sh").write_text("#!/bin/sh\nexit 1\n")
    if subscription:
        from harbor.models.task.config import NetworkMode
        from harbor.models.task.task import Task

        native_task = Task(task_dir=stage).config
        # An explicit user makes native auth/config upload enforce ownership and
        # mode, which is necessary with the Composer's dropped capabilities.
        native_task.agent.user = "root"
        native_task.environment.network_mode = NetworkMode.ALLOWLIST
        native_task.environment.allowed_hosts = [
            "chatgpt.com",
            "auth.openai.com",
            "api.openai.com",
            "simulator",
        ]
        (stage / "task.toml").write_text(native_task.model_dump_toml())
    agent = agent.model_copy(deep=True)
    agent.kwargs["prompt_template_path"] = str(handoff)
    started = time.monotonic()
    exploration = None
    native = None
    try:
        async with replay_environment(
            creation_config, identity, lifecycle=lifecycle, simulator_only=True
        ) as context:
            await context.control(
                "reset",
                {
                    "identity": identity,
                    "state": task["example"]["state"],
                    "profile": identity["profile"],
                    "limits": {"call_timeout_sec": config.tool_timeout_sec},
                },
            )
            issued = await context.control(
                "issue",
                {
                    "identity": identity,
                    "actor": "workflow",
                    "ttl_sec": config.setup_timeout_sec + config.submission_timeout_sec,
                    "max_calls": composer["exploration_max_calls"],
                },
            )
            connection = root / "connection.json"
            connection.write_text(
                json.dumps(
                    {
                        "tool_url": f"http://simulator:{config.tools_port}",
                        "capability": issued["capability"],
                    }
                )
            )
            connection.chmod(0o600)
            compose = {
                "services": {
                    "main": {
                        "image": composer["image"],
                        "working_dir": "/work",
                        "stop_grace_period": "1s",
                        "cap_drop": ["ALL"],
                        "cap_add": ["CHOWN"],
                        "security_opt": ["no-new-privileges:true"],
                        "networks": ["tools"],
                        "environment": {
                            "HOME": "/home/composer",
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                    },
                    "provider": {
                        "image": config.app_image,
                        "command": ["python", "-m", "http.server", "8080"],
                        "cap_drop": ["ALL"],
                        "security_opt": ["no-new-privileges:true"],
                        "read_only": True,
                        "tmpfs": ["/tmp"],
                        "networks": ["tools"],
                        "cpus": config.cpus,
                        "mem_limit": f"{config.memory_mb}m",
                    },
                },
                "networks": {
                    "tools": {"external": True, "name": context.project + "_tools"}
                },
            }
            if subscription:
                del compose["services"]["provider"]
                del compose["services"]["main"]["networks"]
                compose["services"]["harbor-docker-egress-control-sidecar"] = {
                    "networks": ["default", "tools"],
                }
                compose["networks"]["default"] = {}
            (stage / "environment/docker-compose.yaml").write_text(json.dumps(compose))

            async def setup(environment):
                await environment.upload_dir(public.root, "/work")
                await environment.upload_file(connection, "/work/tools-connection.json")
                if previous is not None:
                    await environment.upload_file(
                        previous.path, "/work/previous-workflow.json"
                    )
                feedback_path = root / "feedback.json"
                feedback_path.write_text(json.dumps(feedback))
                await environment.upload_file(feedback_path, "/work/feedback.json")
                owner = shlex.quote(str(environment.default_user or "root"))
                permissions = await environment.exec(
                    "chown -R "
                    + owner
                    + " /work && mkdir -p /home/composer && chown "
                    + owner
                    + " /home/composer",
                    user="root",
                    timeout_sec=math.ceil(config.control_timeout_sec),
                )
                if permissions.return_code:
                    raise RuntimeError("composer_permissions_failed")
                checked = await environment.exec(
                    "test ! -e /root/.codex/auth.json && test ! -e /tmp/codex-home && test ! -e /home/composer/.agents && test ! -e /work/tests && test ! -e /work/solution",
                    timeout_sec=math.ceil(config.control_timeout_sec),
                )
                if checked.return_code:
                    raise RuntimeError("composer_home_not_fresh")
                containers = await docker(
                    "ps",
                    "--filter",
                    "label=com.docker.compose.project="
                    + SUBMISSION_TRIAL_PREFIX
                    + attempt_id
                    + "__env",
                    "--format",
                    "{{.ID}}",
                )
                checked_services = set()
                for container in containers.splitlines():
                    info = json.loads(await docker("inspect", container))[0]
                    service = info["Config"]["Labels"]["com.docker.compose.service"]
                    permitted_services = (
                        {"main", "harbor-docker-egress-control-sidecar"}
                        if subscription
                        else {"main", "provider"}
                    )
                    if service not in permitted_services:
                        continue
                    checked_services.add(service)
                    if (
                        subscription
                        and service == "main"
                        and not info["HostConfig"]["NetworkMode"].startswith(
                            "container:"
                        )
                    ):
                        raise RuntimeError("composer_egress_not_isolated")
                    for mount in info["Mounts"]:
                        if mount["Type"] == "bind" and not mount["Source"].startswith(
                            str(root / "harbor") + "/"
                        ):
                            raise RuntimeError("composer_mount_forbidden")
                    if any(info["NetworkSettings"]["Ports"].values()):
                        raise RuntimeError("composer_port_exposed")
                    for network in info["NetworkSettings"]["Networks"].values():
                        if (
                            subscription
                            and service == "harbor-docker-egress-control-sidecar"
                        ):
                            continue
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
                            raise RuntimeError("composer_egress_not_isolated")
                expected_services = (
                    {"main", "harbor-docker-egress-control-sidecar"}
                    if subscription
                    else {"main", "provider"}
                )
                if checked_services != expected_services:
                    raise RuntimeError("composer_isolation_unconfirmed")
                if subscription:
                    policy = await environment.service_exec(
                        "network-policy show",
                        service="harbor-docker-egress-control-sidecar",
                        timeout_sec=math.ceil(config.control_timeout_sec),
                    )
                    if (
                        policy.return_code
                        or "mode: controlled egress" not in policy.stdout
                    ):
                        raise RuntimeError("composer_egress_not_isolated")
                    (root / "network-policy.txt").write_text(policy.stdout)
                if context.protected_control_url is None:
                    raise RuntimeError("control_address_missing")
                target = context.protected_control_url + "/control/export"
                probe = (
                    "from urllib.request import build_opener, ProxyHandler; "
                    "from urllib.error import HTTPError, URLError; import json; "
                    "opener=build_opener(ProxyHandler({})); reached=False\n"
                    "try:\n"
                    f" opener.open({target!r}, timeout={config.control_timeout_sec}).close(); reached=True\n"
                    "except HTTPError: reached=True\n"
                    "except (URLError, TimeoutError, OSError): pass\n"
                    "print(json.dumps(reached))"
                )
                reachability = {}
                for service in ("main",) if subscription else ("main", "provider"):
                    checked = await environment.service_exec(
                        "python -c " + shlex.quote(probe),
                        service=service,
                        timeout_sec=math.ceil(config.control_timeout_sec + 1),
                    )
                    if checked.return_code:
                        raise RuntimeError("composer_control_probe_failed")
                    reachability[service] = json.loads(checked.stdout)
                (root / "isolation.json").write_text(
                    json.dumps({"control_url": target, "reachability": reachability})
                )
                if any(reachability.values()):
                    raise RuntimeError("composer_control_reachable")
                if subscription:
                    denied = await environment.exec(
                        "python -c "
                        + shlex.quote(
                            "from urllib.request import urlopen; from urllib.error import URLError; "
                            "import sys\ntry: urlopen('https://example.com', timeout=3); sys.exit(1)\n"
                            "except (URLError, TimeoutError, OSError): pass"
                        ),
                        timeout_sec=math.ceil(config.control_timeout_sec),
                    )
                    if denied.return_code:
                        raise RuntimeError("composer_unrelated_egress_allowed")

            async def close_tools():
                nonlocal exploration
                await context.control("revoke", {"identity": identity})
                await context.control(
                    "freeze",
                    {"identity": identity, "drain_sec": config.drain_timeout_sec},
                )
                exploration = await context.control("export")
                (root / "exploration.json").write_text(json.dumps(exploration))

            async def unused(path):
                raise RuntimeError("composer_must_not_verify")

            native = await run_native_trial(
                stage,
                attempt_id,
                unused,
                config=replace(creation_config, app_image=composer["image"]),
                lifecycle=lifecycle,
                agent=agent,
                setup=setup,
                close_tools=close_tools,
                verify=False,
            )
            if exploration is None:
                await close_tools()
    finally:
        connection_path = root / "connection.json"
        try:
            connection_path.unlink(missing_ok=True)
        except OSError:
            lifecycle.cleanup_errors.append("connection_cleanup_failed")
        stop_path = root / "submission-stop.json"
        stop = {"stop_confirmed": False}
        try:
            if stop_path.exists():
                observed = read_json(stop_path, "submission-stop.json")
                stop["stop_confirmed"] = observed.get("stop_confirmed") is True
        except (OSError, DataError, AttributeError):
            lifecycle.cleanup_errors.append("stop_record_unavailable")
        raw_usage = collect_codex_usage(
            root / "harbor" / (SUBMISSION_TRIAL_PREFIX + attempt_id) / "agent"
        )
        limits_after = None
        if subscription:
            try:
                limits_after = await asyncio.to_thread(
                    read_codex_limits, auth_path, timeout_sec=config.control_timeout_sec
                )
            except (DataError, OSError, ValueError):
                LOGGER.warning("phase=creation code=subscription_remaining_unknown")
        metrics = {
            "source": agent.import_path,
            "budget_remaining_known": limits_after is not None
            if subscription
            else True,
            "model_calls": raw_usage["model_calls"] if subscription else 0,
            "input_tokens": raw_usage["input_tokens"] if subscription else None,
            "output_tokens": raw_usage["output_tokens"] if subscription else None,
            "usd": None,
            "wall_ms": (time.monotonic() - started) * 1000,
            "exploration_ref": "exploration.json" if exploration else None,
            "tool_calls": sum(
                e["stage"] == "accepted" and e["details"]["status"] == "accepted"
                for e in exploration["events"]
            )
            if exploration
            else None,
            "harbor_result_ref": native.result_ref if native else None,
            "native_phase_timings_ref": native.result_ref if native else None,
            "cleanup_errors": lifecycle.cleanup_errors,
            "residual_resources": lifecycle.residual_resources,
            "stop_confirmed": stop["stop_confirmed"],
            "raw_usage": raw_usage,
            "stop_ref": "submission-stop.json" if stop_path.exists() else None,
            "composer": composer,
            "subscription_limits_before": limits_before,
            "subscription_limits_after": limits_after,
        }
        try:
            (root / "creation.json").write_text(json.dumps(metrics, indent=2))
        except OSError:
            lifecycle.cleanup_errors.append("creation_log_failed")
            LOGGER.warning("phase=creation code=creation_log_failed")
        LOGGER.info(
            "phase=creation attempt_id=%s stop_confirmed=%s report=%s",
            attempt_id,
            metrics["stop_confirmed"],
            root / "creation.json",
        )
    stopped = (
        native.stop_confirmed
        and not lifecycle.cleanup_errors
        and not lifecycle.residual_resources
    )
    return ControlledSubmission(
        native.artifact_path,
        "unknown" if native.exception_type else "completed",
        stopped,
        metrics=metrics,
    )


def collect_codex_usage(
    logs: Path, *, prices: dict[str, float] | None = None
) -> dict[str, JsonValue]:
    """Keep raw refs; one session's last totals take precedence over turn events."""
    raw_refs, snapshots, malformed = _session_snapshot(logs)
    totals = None
    if len(snapshots) == 1 and not malformed:
        try:
            lines = snapshots[0][1].decode("utf-8").splitlines()
        except (OSError, UnicodeError, DataError):
            lines = []
            malformed = True
        for line in lines:
            try:
                event = json.loads(line)
                payload = event.get("payload", {})
                if (
                    event.get("type") == "event_msg"
                    and payload.get("type") == "token_count"
                ):
                    info = payload.get("info")
                    if isinstance(info, dict) and isinstance(
                        info.get("total_token_usage"), dict
                    ):
                        totals = info["total_token_usage"]
            except (ValueError, AttributeError, TypeError):
                malformed = True
    if malformed:
        totals = None
    usage = {
        "source": "native_session_last_cumulative",
        "raw_refs": raw_refs,
        "model_calls": None,
        "usd": None,
        "prices": prices,
    }
    for name in ("input_tokens", "cached_input_tokens", "output_tokens"):
        value = totals.get(name) if totals else None
        usage[name] = (
            value
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else None
        )
    if prices is not None and all(
        usage[key] is not None
        for key in ("input_tokens", "cached_input_tokens", "output_tokens")
    ):
        if set(prices) != {
            "input_per_million",
            "cached_input_per_million",
            "output_per_million",
        } or any(
            isinstance(v, bool)
            or not isinstance(v, (int, float))
            or not math.isfinite(v)
            or v < 0
            for v in prices.values()
        ):
            raise DataError("invalid_prices", "prices")
        uncached = usage["input_tokens"] - usage["cached_input_tokens"]
        if uncached >= 0:
            usage["usd"] = (
                uncached * prices["input_per_million"]
                + usage["cached_input_tokens"] * prices["cached_input_per_million"]
                + usage["output_tokens"] * prices["output_per_million"]
            ) / 1_000_000
    return usage


def _read_session(name: str, directory: int, limit: int) -> bytes:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory
    )
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise DataError("unsafe_session", "sessions")
        if info.st_size > limit:
            raise DataError("session_too_large", "sessions")
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise DataError("session_too_large", "sessions")
    return content


def _session_snapshot(logs: Path) -> tuple[list[str], list[tuple[Path, bytes]], bool]:
    """Snapshot bounded native logs through directory handles, never follow links."""
    references = []
    snapshots = []
    entries = 0
    remaining = MAX_EVIDENCE_BYTES
    invalid = False
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW

    def visit(directory: int, relative: Path, depth: int) -> None:
        nonlocal entries, remaining, invalid
        if depth > MAX_SESSION_DEPTH:
            raise DataError("session_tree_too_large", "sessions")
        with os.scandir(directory) as children:
            for child in children:
                entries += 1
                if entries > MAX_SESSION_ENTRIES:
                    raise DataError("session_tree_too_large", "sessions")
                reference = relative / child.name
                if child.name.endswith(".jsonl"):
                    references.append(reference.as_posix())
                    try:
                        content = _read_session(child.name, directory, remaining)
                        # Native Harbor uses permissive JSON and unbounded line reads.
                        # Give it only checked, finite regular-file snapshots.
                        for line in content.splitlines():
                            if line.strip() and not isinstance(
                                decode_json(line, "sessions"), dict
                            ):
                                raise DataError("invalid_session", "sessions")
                        remaining -= len(content)
                        snapshots.append((reference, content))
                    except (OSError, DataError):
                        invalid = True
                elif child.is_dir(follow_symlinks=False):
                    descriptor = os.open(child.name, flags, dir_fd=directory)
                    try:
                        visit(descriptor, reference, depth + 1)
                    finally:
                        os.close(descriptor)
                elif child.is_symlink():
                    references.append(reference.as_posix())
                    invalid = True

    try:
        descriptor = os.open(logs, flags)
        try:
            try:
                directory = os.open("sessions", flags, dir_fd=descriptor)
            except FileNotFoundError:
                return [], [], False
            try:
                visit(directory, Path("sessions"), 0)
            finally:
                os.close(directory)
        finally:
            os.close(descriptor)
    except FileNotFoundError:
        invalid = bool(references)
    except (OSError, DataError):
        invalid = True
    return sorted(references), sorted(snapshots), invalid
